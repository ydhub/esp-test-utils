"""HTTP/HTTPS helpers for local integration tests.

Core API: :class:`HttpHelper` and :class:`HttpsHelper` bind, dispatch, drain
the request body, and write the response. :data:`DEFAULT_ROUTERS` is an optional
ESP HTTP test fixture. Pass ``routers=list(DEFAULT_ROUTERS)``; the constant is a
tuple, so ``append`` needs that list copy.

``ThreadingHTTPServer.serve_forever`` blocks the calling thread, so
``HttpHelper`` only adds ``with`` to run it in a daemon thread.
"""

import html
import json
import os
import re
import socket
import ssl
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import esptest.common.compat_typing as t

from ..logger import get_logger

logger = get_logger('http_helper')

_DEFAULT_MAX_PAYLOAD = 10 * 1024 * 1024
_GET_BYTES_PATH_RE = re.compile(r'^/get_bytes_(?P<num>\d+)(?P<unit>[kKmM]?)$')
_GET_TEXT_PATH_RE = re.compile(r'^/get_text_(?P<num>\d+)(?P<unit>[kKmM]?)$')
_SIZE_TOKEN_RE = re.compile(r'^(?P<num>\d+)(?P<unit>[kKmM]?)$')
_STREAM_IO_ERRORS = (ConnectionResetError, BrokenPipeError, socket.timeout)


class ServerStartupError(RuntimeError):
    """Raised when a test server fails to bind or set up TLS."""


@dataclass
class ServerConfig:
    """Listen address and I/O limits. Constructor host/port override these defaults.

    ``put_read_timeout`` is the timeout of each body read, not a budget for the
    whole body. A peer that keeps sending can hold the thread for longer. The
    same value bounds how long a connection may wait for the request line, and
    how long the TLS handshake may take. ``write_timeout`` bounds every response
    write, including 404, 405, and 500. A peer that stops reading releases the
    handler thread when that timer expires, instead of waiting for the TCP
    retransmit timeout. A write that does not finish closes the connection.
    """

    host: str = '0.0.0.0'
    http_port: int = 8000
    https_port: int = 8443
    io_chunk_size: int = 65536
    max_put_payload: int = _DEFAULT_MAX_PAYLOAD
    max_get_payload: int = _DEFAULT_MAX_PAYLOAD
    put_read_timeout: float = 10.0
    write_timeout: float = 600.0
    thread_join_timeout: float = 10.0


@dataclass
class HttpRequest:
    """Request context passed to a router handler.

    ``path`` is the request target without the query string. ``query`` is the
    raw query (no leading ``?``). ``raw_path`` is the original request target.
    ``max_get_payload`` is copied from :class:`ServerConfig` and caps generated
    ``/get_bytes`` / ``/get_text`` bodies. ``truncated`` is true only when
    ``Content-Length`` exceeds ``max_put_payload``. A short read (timeout or
    disconnect) leaves it false; compare ``received`` with ``content_length``.
    """

    method: str
    path: str
    query: str = ''
    raw_path: str = ''
    received: int = 0
    content_length: int = 0
    truncated: bool = False
    max_get_payload: int = _DEFAULT_MAX_PAYLOAD


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
# method is any HTTP method token. DELETE, GET, HEAD, POST, and PUT are built in;
# any other token is dispatched the same way.
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
    """Return the first ``(method, path, handler)`` that matches.

    An exact method match wins over the HEAD→GET fallback, even when the GET
    router was registered first.
    """
    method = method.upper()
    get_fallback = None  # type: t.Optional[HttpRouter]
    for router in routers:
        router_method, pattern, _handler = router
        router_method = router_method.upper()
        if not _path_matches(pattern, path):
            continue
        if router_method == method:
            return router
        if method == 'HEAD' and router_method == 'GET' and get_fallback is None:
            get_fallback = router
    return get_fallback


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

    def setup(self) -> None:
        # Bound a peer that connects and never sends a request line.
        super().setup()
        if self.connection is not None:
            self.connection.settimeout(self.server_config.put_read_timeout)

    def _route_path(self) -> str:
        return self.path.split('?', 1)[0]

    def _read_content_length(self) -> t.Optional[int]:
        """Return a non-negative length, ``0`` when the header is absent, or ``None`` when it is invalid."""
        raw = self.headers.get('Content-Length')
        if raw is None:
            return 0
        try:
            length = int(raw)
        except ValueError:
            return None
        if length < 0:
            return None
        return length

    def _chunked_body(self) -> bool:
        return 'chunked' in self.headers.get('Transfer-Encoding', '').lower()

    @staticmethod
    def _allow_header(methods: t.Set[str]) -> str:
        known = [name for name in _HttpHandler._method_order if name in methods]
        extra = sorted(name for name in methods if name not in _HttpHandler._method_order)
        return ', '.join(known + extra)

    def _safe_write(self, data: bytes, context: str) -> bool:
        try:
            self.wfile.write(data)
            return True
        except _STREAM_IO_ERRORS as exc:
            logger.warning('%s write interrupted: %s', context, exc)
            # A truncated body must not stay on a keep-alive connection.
            self._close_after_response()
            return False

    def _drain_body(self, content_length: int) -> int:
        """Read the request body from ``rfile`` and return how many bytes arrived.

        ``BaseHTTPRequestHandler`` does not consume the body. A plain
        ``rfile.read(Content-Length)`` would keep the whole payload in memory and
        can block if the peer stalls. This reads at most
        ``min(Content-Length, max_put_payload)`` in chunks, applies
        ``put_read_timeout`` to each read (not to the whole body), and treats
        timeout or disconnect as a short read.
        That short read does not set ``truncated``; ``truncated`` is true only
        when ``Content-Length`` exceeds ``max_put_payload``.
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
                # read1 returns already-buffered bytes. read() waits to fill the
                # size and drops that buffer if the rest of the body times out.
                chunk = self.rfile.read1(min(config.io_chunk_size, read_limit - received))
                if not chunk:
                    break
                received += len(chunk)
        except _STREAM_IO_ERRORS:
            logger.warning('Body read stopped after %d/%d bytes', received, read_limit)
        finally:
            if sock is not None:
                sock.settimeout(old_timeout)
        return received

    def _consume_body(self) -> t.Tuple[int, int, bool]:
        """Drain the request body. Return ``received``, ``content_length``, and whether some remains."""
        if self._chunked_body():
            self._close_after_response()
            return 0, 0, True
        content_length = self._read_content_length()
        if content_length is None:
            self._close_after_response()
            return 0, 0, True
        if content_length <= 0:
            return 0, 0, False
        received = self._drain_body(content_length)
        unread = received < content_length
        if unread:
            self._close_after_response()
        return received, content_length, unread

    def _note_unread_body(self) -> bool:
        """Discard the request body. Return True when some of it is still unread.

        Early 404/405 responses used to leave the body in ``rfile``. On an
        HTTP/1.1 keep-alive connection those bytes would be parsed as the next
        request. Bodies larger than ``max_put_payload`` are not fully read;
        the caller must close the connection in that case. The server speaks
        HTTP/1.0, so it already closes after each response.
        """
        _received, _content_length, unread = self._consume_body()
        return unread

    def _close_after_response(self) -> None:
        # BaseHTTPRequestHandler sets this in handle(), not __init__.
        self.close_connection = True  # pylint: disable=attribute-defined-outside-init

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
        sock = self.connection
        old_timeout = None
        if sock is not None:
            old_timeout = sock.gettimeout()
            # Separate from put_read_timeout so a slow reader is not cut off,
            # and a peer that stops reading does not block until TCP gives up.
            sock.settimeout(self.server_config.write_timeout)
        try:
            self.send_response(status)
            if content_type is not None:
                self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload) if content_length is None else content_length))
            if extra_headers:
                for key, value in extra_headers.items():
                    self.send_header(key, value)
            self.end_headers()
            if (
                write_body
                and payload
                and not self._safe_write(
                    payload,
                    context=f'{self.command} {self._route_path()}',
                )
            ):
                self._close_after_response()
        finally:
            if sock is not None:
                sock.settimeout(old_timeout)

    def _write_response(
        self,
        response: Response,
        extra_headers: t.Optional[t.Dict[str, str]] = None,
    ) -> None:
        self._send(
            response.status,
            body=response.body_bytes(),
            content_type=response.content_type_value(),
            extra_headers=extra_headers,
            write_body=self.command != 'HEAD',
        )

    def _send_error(self, status: HTTPStatus) -> None:
        """Send the stdlib HTML error page under ``write_timeout``."""
        self._close_after_response()
        try:
            message, explain = self.responses[int(status)]
        except KeyError:
            message, explain = '???', '???'
        self.log_error('code %d, message %s', int(status), message)
        content = self.error_message_format % {
            'code': int(status),
            'message': html.escape(message, quote=False),
            'explain': html.escape(explain, quote=False),
        }
        self._send(
            int(status),
            body=content.encode('utf-8', 'replace'),
            content_type=self.error_content_type,
            extra_headers={'Connection': 'close'},
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
                self._note_unread_body()
                self._close_after_response()
                self._send(
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    body=b'',
                    content_type=None,
                    extra_headers={
                        'Allow': self._allow_header(allowed),
                        'Connection': 'close',
                    },
                )
                return
            if path == '/' and method in ('GET', 'HEAD'):
                extra = {'Connection': 'close'} if self._note_unread_body() else None
                page = Response(_routers_page(self.routers), content_type='text/plain; charset=utf-8')
                self._write_response(page, extra_headers=extra)
                return
            self._note_unread_body()
            self._send_error(HTTPStatus.NOT_FOUND)
            return

        received, content_length, unread = self._consume_body()
        truncated = content_length > self.server_config.max_put_payload
        extra_headers = {'Connection': 'close'} if unread else None

        _method, _pattern, handler = router
        raw_path = self.path
        request = HttpRequest(
            method=method,
            path=path,
            query=raw_path.partition('?')[2],
            raw_path=raw_path,
            received=received,
            content_length=content_length,
            truncated=truncated,
            max_get_payload=self.server_config.max_get_payload,
        )
        if truncated:
            self._close_after_response()
            extra_headers = {'Connection': 'close'}
        try:
            response = handler(request)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception('router handler failed for %s %s', method, path)
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self._write_response(response, extra_headers=extra_headers)

    do_GET = _dispatch
    do_HEAD = _dispatch
    do_PUT = _dispatch
    do_POST = _dispatch
    do_DELETE = _dispatch

    def __getattr__(self, name: str) -> t.Any:
        """Dispatch methods that have no dedicated ``do_*`` (for example PATCH)."""
        if name.startswith('do_'):
            return self._dispatch
        raise AttributeError(name)


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
        if self._closed:
            raise ServerStartupError(f'{self.server_kind} server is closed')
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self.serve_forever,
                name=f'{self.server_kind.lower()}-test-server',
                daemon=True,
            )
            self._thread.start()
            logger.info(
                'server started (%s://%s:%s)',
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
        self._ssl_context = None  # type: t.Optional[ssl.SSLContext]
        try:
            self._ssl_context = ssl_context or self._build_ssl_context(certfile, keyfile, cafile)
        except ServerStartupError:
            self.server_close()
            raise
        except (OSError, ssl.SSLError) as exc:
            self.server_close()
            raise ServerStartupError(f'HTTPS SSL context setup failed: {exc}') from exc

    def finish_request(self, request: t.Any, client_address: t.Any) -> None:
        """Handshake on the accepted socket so ``serve_forever`` can still shut down."""
        assert self._ssl_context is not None
        try:
            request.settimeout(self.server_config.put_read_timeout)
            tls_sock = self._ssl_context.wrap_socket(request, server_side=True)
        except (ssl.SSLError, socket.timeout, OSError) as exc:
            logger.warning('TLS handshake failed from %s: %s', client_address, exc)
            request.close()
            return
        super().finish_request(tls_sock, client_address)

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


def _generated_payload(size: t.Optional[int], req: HttpRequest, *, text: bool) -> Response:
    if size is None:
        return Response(status=HTTPStatus.NOT_FOUND)
    if size > req.max_get_payload:
        return Response(status=HTTPStatus.BAD_REQUEST)
    if text:
        return Response('A' * size, content_type='text/plain')
    return Response(b'A' * size)


def _size_handler(req: HttpRequest) -> Response:
    return _generated_payload(parse_get_bytes_path(req.path), req, text=False)


def _query_size(req: HttpRequest) -> t.Optional[int]:
    sizes = parse_qs(req.query).get('size')
    if not sizes:
        return None
    return _parse_size_token(sizes[0])


def _get_bytes_query_handler(req: HttpRequest) -> Response:
    return _generated_payload(_query_size(req), req, text=False)


def _get_text_handler(req: HttpRequest) -> Response:
    return _generated_payload(parse_get_text_path(req.path), req, text=True)


def _get_text_query_handler(req: HttpRequest) -> Response:
    return _generated_payload(_query_size(req), req, text=True)


def _long_url_get_handler(req: HttpRequest) -> Response:
    target = req.raw_path or req.path
    return Response(b'OK' + str(len(target)).encode(), content_type='text/plain')


def default_put_handler(req: HttpRequest) -> Response:
    return _upload_response(req.received, req.content_length, req.truncated)


def default_post_handler(req: HttpRequest) -> Response:
    return _upload_response(req.received, req.content_length, req.truncated, path=req.path)


def default_delete_handler(req: HttpRequest) -> Response:
    if req.truncated:
        return _upload_response(req.received, req.content_length, True, path=req.path)
    payload = {'deleted': True, 'path': req.path}
    return Response(json.dumps(payload).encode(), content_type='application/json')


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
