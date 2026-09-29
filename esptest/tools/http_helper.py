"""HTTP/HTTPS helpers for local integration tests.

Core API: :class:`HttpHelper` and :class:`HttpsHelper` bind, dispatch, drain
the request body, and write the response. :data:`DEFAULT_ROUTERS` is an optional
ESP HTTP test fixture passed in via ``routers=``.

``ThreadingHTTPServer.serve_forever`` blocks the calling thread, so
``HttpHelper`` only adds ``with`` to run it in a daemon thread.
"""

import json
import os
import re
import socket
import ssl
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import esptest.common.compat_typing as t

from ..logger import get_logger

logger = get_logger('http_helper')

_GET_BYTES_PATH_RE = re.compile(r'^/get_bytes_(?P<num>\d+)(?P<unit>[kKmM]?)$')
_GET_TEXT_PATH_RE = re.compile(r'^/get_text_(?P<num>\d+)(?P<unit>[kKmM]?)$')
_SIZE_TOKEN_RE = re.compile(r'^(?P<num>\d+)(?P<unit>[kKmM]?)$')
_STREAM_IO_ERRORS = (ConnectionResetError, BrokenPipeError, OSError)


class ServerStartupError(RuntimeError):
    """Raised when a test server fails to bind or set up TLS."""


@dataclass
class ServerConfig:
    """Listen address and I/O limits. Constructor host/port override these defaults."""

    host: str = '0.0.0.0'
    http_port: int = 8000
    https_port: int = 8443
    io_chunk_size: int = 65536
    max_put_payload: int = 10 * 1024 * 1024
    put_read_timeout: float = 5.0
    thread_join_timeout: float = 5.0


@dataclass
class HttpRequest:
    """Request context passed to a router handler."""

    method: str
    path: str
    received: int = 0
    content_length: int = 0
    truncated: bool = False


@dataclass
class Response:
    """Handler result. ``body`` is ``bytes`` or ``str``."""

    body: t.Union[bytes, str] = b''
    status: int = HTTPStatus.OK
    content_type: t.Optional[str] = None

    def body_bytes(self) -> bytes:
        if isinstance(self.body, str):
            return self.body.encode('utf-8')
        return self.body

    def content_type_value(self) -> str:
        if self.content_type is not None:
            return self.content_type
        if isinstance(self.body, str):
            return 'text/plain; charset=utf-8'
        return 'application/octet-stream'


Handler = t.Callable[[HttpRequest], Response]
RoutePattern = t.Union[str, 're.Pattern[str]']
HttpRouter = t.Tuple[str, RoutePattern, Handler]


def _pattern_text(pattern: RoutePattern) -> str:
    if isinstance(pattern, str):
        return pattern
    return pattern.pattern


def _routers_page(routers: t.Sequence[HttpRouter]) -> bytes:
    lines = ['supported routers']
    for method, pattern, _handler in routers:
        lines.append(f'{method.upper()} {_pattern_text(pattern)}')
    return ('\n'.join(lines) + '\n').encode()


def _path_matches(pattern: RoutePattern, path: str) -> bool:
    if isinstance(pattern, str):
        return pattern == path
    return pattern.fullmatch(path) is not None


def match_router(
    routers: t.Sequence[HttpRouter],
    path: str,
    method: str = 'GET',
) -> t.Optional[HttpRouter]:
    """Return the first ``(method, path, handler)`` that matches."""
    method = method.upper()
    for router in routers:
        router_method, pattern, _handler = router
        router_method = router_method.upper()
        if not _path_matches(pattern, path):
            continue
        if router_method == method or (method == 'HEAD' and router_method == 'GET'):
            return router
    return None


class _HttpHandler(BaseHTTPRequestHandler):
    """Dispatches ``do_*`` to ``server.routers``; reuse stdlib send_*/send_error."""

    if t.TYPE_CHECKING:
        server: 'HttpHelper'

    _method_order = ('DELETE', 'GET', 'HEAD', 'POST', 'PUT')

    @property
    def routers(self) -> t.List[HttpRouter]:
        return self.server.routers

    @property
    def server_config(self) -> ServerConfig:
        return self.server.server_config

    def log_message(self, format: str, *args: t.Any) -> None:  # pylint: disable=redefined-builtin
        logger.debug('%s - %s', self.client_address[0], format % args)

    def _route_path(self) -> str:
        return self.path.split('?', 1)[0]

    def _read_content_length(self) -> int:
        try:
            return int(self.headers.get('Content-Length', 0))
        except ValueError:
            return 0

    @staticmethod
    def _allow_header(methods: t.Set[str]) -> str:
        return ', '.join(name for name in _HttpHandler._method_order if name in methods)

    def _safe_write(self, data: bytes, context: str) -> bool:
        try:
            self.wfile.write(data)
            return True
        except _STREAM_IO_ERRORS as exc:
            logger.warning('%s write interrupted: %s', context, exc)
            return False

    def _drain_body(self, content_length: int) -> int:
        """Read the request body from ``rfile`` and return how many bytes arrived.

        ``BaseHTTPRequestHandler`` does not consume the body. A plain
        ``rfile.read(Content-Length)`` would keep the whole payload in memory and
        can block if the peer stalls. This reads at most
        ``min(Content-Length, max_put_payload)`` in chunks, applies
        ``put_read_timeout``, and treats timeout/disconnect as a short read so
        handlers can report ``received`` / ``truncated`` without storing the body.
        """
        config = self.server_config
        read_limit = min(content_length, config.max_put_payload)
        sock = self.connection
        old_timeout = None
        if sock is not None:
            old_timeout = sock.gettimeout()
            sock.settimeout(config.put_read_timeout)
        received = 0
        try:
            while received < read_limit:
                chunk = self.rfile.read(min(config.io_chunk_size, read_limit - received))
                if not chunk:
                    break
                received += len(chunk)
        except (TimeoutError, socket.timeout, *_STREAM_IO_ERRORS):
            logger.warning('Body read stopped after %d/%d bytes', received, read_limit)
        finally:
            if sock is not None:
                sock.settimeout(old_timeout)
        return received

    def _send(  # pylint: disable=too-many-arguments
        self,
        status: int,
        *,
        body: t.Optional[bytes] = None,
        content_type: t.Optional[str] = 'text/plain',
        content_length: t.Optional[int] = None,
        extra_headers: t.Optional[t.Dict[str, str]] = None,
        write_body: bool = True,
    ) -> None:
        payload = body or b''
        self.send_response(status)
        if content_type is not None:
            self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload) if content_length is None else content_length))
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        if write_body and payload:
            self._safe_write(payload, context=f'{self.command} {self._route_path()}')

    def _write_response(self, response: Response) -> None:
        self._send(
            response.status,
            body=response.body_bytes(),
            content_type=response.content_type_value(),
            write_body=self.command != 'HEAD',
        )

    def _dispatch(self) -> None:
        path = self._route_path()
        method = self.command
        router = match_router(self.routers, path, method)
        if router is None:
            allowed = set()  # type: t.Set[str]
            for router_method, pattern, _handler in self.routers:
                if not _path_matches(pattern, path):
                    continue
                router_method = router_method.upper()
                allowed.add(router_method)
                if router_method == 'GET':
                    allowed.add('HEAD')
            if allowed:
                self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
                self.send_header('Allow', self._allow_header(allowed))
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            if path == '/list_routers' and method in ('GET', 'HEAD'):
                self._write_response(Response(_routers_page(self.routers), content_type='text/plain; charset=utf-8'))
                return
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        received = 0
        content_length = 0
        truncated = False
        if method in ('PUT', 'POST', 'DELETE'):
            content_length = self._read_content_length()
            received = self._drain_body(content_length)
            truncated = content_length > self.server_config.max_put_payload
            if method == 'DELETE' and truncated:
                self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                return

        _method, _pattern, handler = router
        request = HttpRequest(
            method=method,
            path=self.path,
            received=received,
            content_length=content_length,
            truncated=truncated,
        )
        self._write_response(handler(request))

    do_GET = _dispatch
    do_HEAD = _dispatch
    do_PUT = _dispatch
    do_POST = _dispatch
    do_DELETE = _dispatch


class HttpHelper(ThreadingHTTPServer):
    """Threaded HTTP test server. Use ``with``; ``serve_forever`` is blocking."""

    allow_reuse_address = True
    server_kind = 'HTTP'

    def __init__(
        self,
        host: t.Optional[str] = None,
        port: t.Optional[int] = None,
        *,
        routers: t.Optional[t.List[HttpRouter]] = None,
        config: t.Optional[ServerConfig] = None,
    ) -> None:
        self.routers = [] if routers is None else routers
        self.server_config = config or ServerConfig()
        bind_host = host if host is not None else self.server_config.host
        bind_port = port if port is not None else self.server_config.http_port
        try:
            super().__init__((bind_host, bind_port), _HttpHandler)
        except OSError as exc:
            message = f'{self.server_kind} bind {bind_host}:{bind_port} failed: {exc}'
            logger.critical(message)
            raise ServerStartupError(message) from exc
        self._thread = None  # type: t.Optional[threading.Thread]
        self._closed = False

    @property
    def address(self) -> t.Tuple[str, int]:
        host, port = self.server_address[:2]
        return str(host), int(port)

    def __enter__(self) -> t.Self:
        if self._thread is None or not self._thread.is_alive():
            self._closed = False
            self._thread = threading.Thread(
                target=self.serve_forever,
                name=f'{self.server_kind.lower()}-test-server',
                daemon=True,
            )
            self._thread.start()
            logger.info(
                'server started (%s://%s:%s/list_routers)',
                self.server_kind.lower(),
                self.address[0],
                self.address[1],
            )
        return self

    def __exit__(self, *args: t.Any) -> None:
        if self._closed:
            return
        self._closed = True
        if self._thread is not None and self._thread.is_alive():
            self.shutdown()
            self._thread.join(self.server_config.thread_join_timeout)
            if self._thread.is_alive():
                logger.warning(
                    'Server thread %s did not exit within %ss',
                    self._thread.name,
                    self.server_config.thread_join_timeout,
                )
        self.server_close()


class HttpsHelper(HttpHelper):
    """HTTP server with TLS. Pass ``certfile``/``keyfile`` or ``ssl_context``.

    ``cafile`` turns on client-certificate checks (``ssl.CERT_REQUIRED``).
    """

    server_kind = 'HTTPS'

    def __init__(  # pylint: disable=too-many-arguments
        self,
        host: t.Optional[str] = None,
        port: t.Optional[int] = None,
        *,
        routers: t.Optional[t.List[HttpRouter]] = None,
        config: t.Optional[ServerConfig] = None,
        cafile: t.Optional[str] = None,
        certfile: t.Optional[str] = None,
        keyfile: t.Optional[str] = None,
        ssl_context: t.Optional[ssl.SSLContext] = None,
    ) -> None:
        cfg = config or ServerConfig()
        if port is None:
            port = cfg.https_port
        super().__init__(host, port, routers=routers, config=cfg)
        try:
            context = ssl_context or self._build_ssl_context(certfile, keyfile, cafile)
            self.socket = context.wrap_socket(self.socket, server_side=True)
        except ServerStartupError:
            self.server_close()
            raise
        except (OSError, ssl.SSLError) as exc:
            self.server_close()
            raise ServerStartupError(f'HTTPS SSL context setup failed: {exc}') from exc

    @staticmethod
    def _validate_ssl_file(label: str, path: str) -> None:
        if not os.path.isfile(path):
            raise ServerStartupError(f'{label} file not found: {path}')
        if not os.access(path, os.R_OK):
            raise ServerStartupError(f'{label} file not readable: {path}')

    @classmethod
    def _build_ssl_context(
        cls,
        certfile: t.Optional[str],
        keyfile: t.Optional[str],
        cafile: t.Optional[str] = None,
    ) -> ssl.SSLContext:
        if not certfile or not keyfile:
            raise ServerStartupError('HTTPS requires certfile/keyfile or ssl_context')
        cls._validate_ssl_file('Certificate', certfile)
        cls._validate_ssl_file('Key', keyfile)
        if cafile:
            cls._validate_ssl_file('CA', cafile)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.set_ciphers('ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20')
        try:
            ctx.load_cert_chain(certfile=certfile, keyfile=keyfile)
            if cafile:
                ctx.verify_mode = ssl.CERT_REQUIRED
                ctx.load_verify_locations(cafile=cafile)
        except (OSError, ssl.SSLError) as exc:
            raise ServerStartupError(f'HTTPS SSL context setup failed: {exc}') from exc
        return ctx


def _upload_response(received: int, content_length: int, truncated: bool, path: t.Optional[str] = None) -> Response:
    payload = {
        'received': received,
        'truncated': truncated,
        'content_length': content_length,
    }  # type: t.Dict[str, t.Any]
    if path is not None:
        payload['path'] = path
    status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE if truncated else HTTPStatus.OK
    return Response(json.dumps(payload).encode(), status=status, content_type='application/json')


def _static_handler(body: t.Union[bytes, str], content_type: t.Optional[str] = None) -> Handler:
    def _handle(_req: HttpRequest) -> Response:
        return Response(body, content_type=content_type)

    return _handle


def _parse_size_token(token: str) -> t.Optional[int]:
    match = _SIZE_TOKEN_RE.match(token)
    if not match:
        return None
    num = int(match.group('num'))
    unit = match.group('unit').lower()
    if unit == 'k':
        return num * 1024
    if unit == 'm':
        return num * 1024 * 1024
    return num


def _parse_sized_path(path: str, pattern: 're.Pattern[str]') -> t.Optional[int]:
    match = pattern.match(path)
    if not match:
        return None
    return _parse_size_token(match.group('num') + match.group('unit'))


def parse_get_bytes_path(path: str) -> t.Optional[int]:
    """Parse ``/get_bytes_<n>[k|m]`` into a byte length."""
    return _parse_sized_path(path, _GET_BYTES_PATH_RE)


def parse_get_text_path(path: str) -> t.Optional[int]:
    """Parse ``/get_text_<n>[k|m]`` into a character length."""
    return _parse_sized_path(path, _GET_TEXT_PATH_RE)


def _size_handler(req: HttpRequest) -> Response:
    size = parse_get_bytes_path(req.path.split('?', 1)[0])
    if size is None:
        return Response(status=HTTPStatus.NOT_FOUND)
    return Response(b'A' * size)


def _query_size(req: HttpRequest) -> t.Optional[int]:
    sizes = parse_qs(urlsplit(req.path).query).get('size')
    if not sizes:
        return None
    return _parse_size_token(sizes[0])


def _get_bytes_query_handler(req: HttpRequest) -> Response:
    size = _query_size(req)
    if size is None:
        return Response(status=HTTPStatus.NOT_FOUND)
    return Response(b'A' * size)


def _get_text_handler(req: HttpRequest) -> Response:
    size = parse_get_text_path(req.path.split('?', 1)[0])
    if size is None:
        return Response(status=HTTPStatus.NOT_FOUND)
    return Response('A' * size, content_type='text/plain')


def _get_text_query_handler(req: HttpRequest) -> Response:
    size = _query_size(req)
    if size is None:
        return Response(status=HTTPStatus.NOT_FOUND)
    return Response('A' * size, content_type='text/plain')


def _long_url_get_handler(req: HttpRequest) -> Response:
    return Response(b'OK' + str(len(req.path)).encode(), content_type='text/plain')


def default_put_handler(req: HttpRequest) -> Response:
    return _upload_response(req.received, req.content_length, req.truncated)


def default_post_handler(req: HttpRequest) -> Response:
    return _upload_response(req.received, req.content_length, req.truncated, path=req.path.split('?', 1)[0])


def default_delete_handler(req: HttpRequest) -> Response:
    path = req.path.split('?', 1)[0]
    return Response(json.dumps({'deleted': True, 'path': path}).encode(), content_type='application/json')


DEFAULT_ROUTERS = (
    ('GET', re.compile(r'/get_with_very_long_url_.*'), _long_url_get_handler),
    ('GET', '/hello', _static_handler('hello')),
    ('GET', '/check_get_endpoint', _static_handler('OK')),
    ('GET', '/invalid_url', lambda _req: Response(status=HTTPStatus.NOT_FOUND)),
    ('GET', '/get_bytes_1k', _static_handler(b'A' * 1024)),
    ('GET', '/get_bytes', _get_bytes_query_handler),
    ('GET', re.compile(r'/get_bytes_\d+[kKmM]?'), _size_handler),
    ('GET', '/get_text', _get_text_query_handler),
    ('GET', re.compile(r'/get_text_\d+[kKmM]?'), _get_text_handler),
    ('PUT', '/put_endpoint', default_put_handler),
    ('PUT', re.compile(r'/put_with_very_long_url_.*'), default_put_handler),
    ('POST', '/post_endpoint', default_post_handler),
    ('DELETE', '/delete_endpoint', default_delete_handler),
)  # type: t.Tuple[HttpRouter, ...]
