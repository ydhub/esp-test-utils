import io
import json
import logging
import re
import shutil
import ssl
import subprocess
from http import HTTPStatus
from http.client import HTTPConnection, HTTPSConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import List, Optional, Tuple
from unittest.mock import MagicMock

import pytest

from esptest.tools.http_helper import (
    DEFAULT_ROUTERS,
    HttpHelper,
    HttpRequest,
    HttpRouter,
    HttpsHelper,
    Response,
    ServerConfig,
    ServerStartupError,
    _HttpHandler,
    default_post_handler,
    default_put_handler,
    match_router,
    parse_get_bytes_path,
    parse_get_text_path,
)


def _host_port(server: HttpHelper) -> Tuple[str, int]:
    return server.address


def _http(routers: Optional[List[HttpRouter]] = None, config: Optional[ServerConfig] = None) -> HttpHelper:
    if routers is None:
        routers = list(DEFAULT_ROUTERS)
    return HttpHelper('127.0.0.1', 0, routers=routers, config=config)


def _write_self_signed_certs(cert_dir: Path) -> None:
    openssl_bin = shutil.which('openssl')
    if not openssl_bin:
        pytest.skip('openssl is required to generate user-provided test certs')
    assert openssl_bin is not None
    key = cert_dir / 'server.key'
    cert = cert_dir / 'server.crt'
    subprocess.check_call(
        [
            openssl_bin,
            'req',
            '-x509',
            '-newkey',
            'rsa:2048',
            '-keyout',
            str(key),
            '-out',
            str(cert),
            '-days',
            '1',
            '-nodes',
            '-subj',
            '/CN=localhost',
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    (cert_dir / 'server_ca.crt').write_bytes(cert.read_bytes())


def _openssl(cert_dir: Path, args: List[str]) -> None:
    openssl_bin = shutil.which('openssl')
    if not openssl_bin:
        pytest.skip('openssl is required to generate user-provided test certs')
    assert openssl_bin is not None
    subprocess.check_call(
        [openssl_bin, *args],
        cwd=str(cert_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _write_mtls_certs(cert_dir: Path) -> None:
    (cert_dir / 'server.ext').write_text(
        'basicConstraints=CA:FALSE\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:localhost\n',
        encoding='utf-8',
    )
    (cert_dir / 'client.ext').write_text(
        'basicConstraints=CA:FALSE\nextendedKeyUsage=clientAuth\n',
        encoding='utf-8',
    )
    _openssl(
        cert_dir,
        [
            'req',
            '-x509',
            '-newkey',
            'rsa:2048',
            '-keyout',
            'ca.key',
            '-out',
            'ca.crt',
            '-days',
            '1',
            '-nodes',
            '-subj',
            '/CN=test-ca',
        ],
    )
    _openssl(
        cert_dir,
        [
            'req',
            '-newkey',
            'rsa:2048',
            '-keyout',
            'server.key',
            '-out',
            'server.csr',
            '-nodes',
            '-subj',
            '/CN=localhost',
        ],
    )
    _openssl(
        cert_dir,
        [
            'x509',
            '-req',
            '-in',
            'server.csr',
            '-CA',
            'ca.crt',
            '-CAkey',
            'ca.key',
            '-CAcreateserial',
            '-out',
            'server.crt',
            '-days',
            '1',
            '-extfile',
            'server.ext',
        ],
    )
    _openssl(
        cert_dir,
        [
            'req',
            '-newkey',
            'rsa:2048',
            '-keyout',
            'client.key',
            '-out',
            'client.csr',
            '-nodes',
            '-subj',
            '/CN=test-client',
        ],
    )
    _openssl(
        cert_dir,
        [
            'x509',
            '-req',
            '-in',
            'client.csr',
            '-CA',
            'ca.crt',
            '-CAkey',
            'ca.key',
            '-CAcreateserial',
            '-out',
            'client.crt',
            '-days',
            '1',
            '-extfile',
            'client.ext',
        ],
    )


def _fake_handler(
    *,
    rfile: Optional[io.BytesIO] = None,
    wfile: Optional[MagicMock] = None,
    config: Optional[ServerConfig] = None,
    connection: object = None,
) -> MagicMock:
    handler = MagicMock()
    handler.rfile = rfile
    handler.wfile = wfile
    handler.server_config = config or ServerConfig()
    handler.connection = connection
    return handler


def _req(path: str, method: str = 'GET') -> HttpRequest:
    return HttpRequest(method=method, path=path)


def test_server_config_defaults() -> None:
    cfg = ServerConfig()
    assert cfg.host == '0.0.0.0'
    assert cfg.http_port == 8000
    assert cfg.https_port == 8443
    assert cfg.max_put_payload == 10 * 1024 * 1024


def test_bind_uses_config_when_host_port_omitted() -> None:
    with HttpHelper(config=ServerConfig(host='127.0.0.1', http_port=0)) as server:
        assert server.address[0] == '127.0.0.1'
        assert server.address[1] > 0
        assert server.routers == []


def test_logs_server_started(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger='esptest.http_helper'):
        with HttpHelper('127.0.0.1', 0) as server:
            host, port = server.address
            assert f'server started (http://{host}:{port}/list_routers)' in caplog.text


def test_root_lists_supported_routers() -> None:
    routers = [
        ('GET', '/hello', lambda _req: Response('hello')),
        ('PUT', '/upload', lambda _req: Response(b'CUSTOM')),
        ('GET', re.compile(r'/item_\d+'), lambda _req: Response('item')),
    ]  # type: List[HttpRouter]
    with _http(routers=routers) as server:
        host, port = _host_port(server)
        conn = HTTPConnection(host, port, timeout=5)
        conn.request('GET', '/')
        response = conn.getresponse()
        assert response.status == HTTPStatus.NOT_FOUND
        response.read()

        conn.request('GET', '/list_routers')
        response = conn.getresponse()
        assert response.status == 200
        assert response.getheader('Content-Type') == 'text/plain; charset=utf-8'
        assert response.read() == b'supported routers\nGET /hello\nPUT /upload\nGET /item_\\d+\n'
        conn.close()


def test_root_route_overrides_router_list() -> None:
    with _http(routers=[('GET', '/', lambda _req: Response('home'))]) as server:
        host, port = _host_port(server)
        conn = HTTPConnection(host, port, timeout=5)
        conn.request('GET', '/')
        response = conn.getresponse()
        assert response.status == 200
        assert response.read() == b'home'
        conn.close()


def test_empty_server_root_lists_no_routers() -> None:
    with HttpHelper('127.0.0.1', 0) as server:
        host, port = _host_port(server)
        conn = HTTPConnection(host, port, timeout=5)
        conn.request('GET', '/')
        response = conn.getresponse()
        assert response.status == HTTPStatus.NOT_FOUND
        response.read()
        conn.request('GET', '/list_routers')
        response = conn.getresponse()
        assert response.status == 200
        assert response.read() == b'supported routers\n'
        conn.close()


def test_empty_server_has_no_default_routers() -> None:
    with HttpHelper('127.0.0.1', 0) as server:
        host, port = _host_port(server)
        conn = HTTPConnection(host, port, timeout=5)
        conn.request('GET', '/hello')
        response = conn.getresponse()
        assert response.status == HTTPStatus.NOT_FOUND
        response.read()
        conn.close()


def test_invalid_url_returns_404() -> None:
    with _http() as server:
        host, port = _host_port(server)
        conn = HTTPConnection(host, port, timeout=5)
        conn.request('GET', '/invalid_url')
        response = conn.getresponse()
        assert response.status == HTTPStatus.NOT_FOUND
        assert response.getheader('Content-Length') == '0'
        assert response.read() == b''
        conn.close()


def test_parse_get_bytes_path_units() -> None:
    assert parse_get_bytes_path('/get_bytes_100') == 100
    assert parse_get_bytes_path('/get_bytes_5k') == 5120
    assert parse_get_bytes_path('/get_bytes_2M') == 2 * 1024 * 1024
    assert parse_get_bytes_path('/put_endpoint') is None
    assert parse_get_text_path('/get_text_100') == 100
    assert parse_get_text_path('/get_text_5k') == 5120
    assert parse_get_text_path('/get_text_2M') == 2 * 1024 * 1024
    assert parse_get_text_path('/get_bytes_100') is None


def test_route_match_priority() -> None:
    routers = list(DEFAULT_ROUTERS)

    sized = match_router(routers, '/get_bytes_1k')
    assert sized is not None
    assert sized[0] == 'GET'
    assert sized[2](_req('/get_bytes_1k')).body == b'A' * 1024

    query = match_router(routers, '/get_bytes')
    assert query is not None
    assert query[2](_req('/get_bytes?size=2k')).body == b'A' * 2048

    sized_5k = match_router(routers, '/get_bytes_5k')
    assert sized_5k is not None
    assert sized_5k[2](_req('/get_bytes_5k')).body == b'A' * 5120

    text_sized = match_router(routers, '/get_text_5k')
    assert text_sized is not None
    text_response = text_sized[2](_req('/get_text_5k'))
    assert text_response.body == 'A' * 5120
    assert text_response.content_type == 'text/plain'

    text_query = match_router(routers, '/get_text')
    assert text_query is not None
    text_query_response = text_query[2](_req('/get_text?size=2k'))
    assert text_query_response.body == 'A' * 2048
    assert text_query_response.content_type == 'text/plain'

    hello = match_router(routers, '/hello')
    assert hello is not None
    hello_response = hello[2](_req('/hello'))
    assert hello_response.body == 'hello'
    assert hello_response.content_type_value() == 'text/plain; charset=utf-8'

    long_path = '/get_with_very_long_url_' + 'x' * 32
    long_route = match_router(routers, long_path)
    assert long_route is not None
    assert long_route[2](_req(long_path)).body == b'OK' + str(len(long_path)).encode()

    assert match_router(routers, '/put_endpoint', 'GET') is None
    assert match_router(routers, '/put_endpoint', 'PUT') is not None
    assert match_router(routers, '/put_with_very_long_url_' + 'y' * 16, 'PUT') is not None
    assert match_router(routers, '/post_endpoint', 'POST') is not None
    assert match_router(routers, '/post_endpoint', 'GET') is None
    assert match_router(routers, '/delete_endpoint', 'DELETE') is not None
    assert match_router(routers, '/missing') is None


def test_path_match_str_exact_and_compiled_regex() -> None:
    def ok(_req: HttpRequest) -> Response:
        return Response(b'ok')

    routers = [
        ('GET', '/hello', ok),
        ('GET', r'^/hello$', ok),
        ('GET', re.compile(r'/item_\d+'), ok),
    ]  # type: List[HttpRouter]
    assert match_router(routers, '/hello') is not None
    assert match_router(routers, '/hello/extra') is None
    assert match_router(routers, r'^/hello$') is not None
    assert match_router(routers, '/item_12') is not None
    assert match_router(routers, '/item_12/x') is None


def test_drain_request_body_truncation() -> None:
    payload = b'x' * (ServerConfig.max_put_payload + 50)
    handler = _fake_handler(
        rfile=io.BytesIO(payload),
        config=ServerConfig(max_put_payload=1024),
    )
    assert _HttpHandler._drain_body(handler, len(payload)) == 1024


def test_drain_request_body_connection_reset() -> None:
    class BrokenReader(io.BytesIO):
        def read(self, n: Optional[int] = -1) -> bytes:
            raise ConnectionResetError('reset')

    handler = _fake_handler(rfile=BrokenReader(b'abc'))
    assert _HttpHandler._drain_body(handler, 3) == 0


def test_safe_write_disconnect() -> None:
    wfile = MagicMock()
    wfile.write.side_effect = BrokenPipeError('gone')
    assert _HttpHandler._safe_write(_fake_handler(wfile=wfile), b'data', 'test') is False


def test_http_https_class_hierarchy() -> None:
    assert issubclass(HttpHelper, ThreadingHTTPServer)
    assert issubclass(HttpsHelper, HttpHelper)


def test_parallel_http_servers() -> None:
    with _http() as server_a, _http() as server_b:
        assert server_a.address[1] != server_b.address[1]


def test_put_endpoint_json() -> None:
    with _http() as server:
        host, port = _host_port(server)
        conn = HTTPConnection(host, port, timeout=5)
        body = b'P' * 64
        conn.request('PUT', '/put_endpoint', body=body, headers={'Content-Length': str(len(body))})
        response = conn.getresponse()
        assert response.status == 200
        assert json.loads(response.read().decode()) == {
            'received': 64,
            'truncated': False,
            'content_length': 64,
        }
        conn.close()


def test_get_put_endpoint_returns_405() -> None:
    with _http() as server:
        host, port = _host_port(server)
        conn = HTTPConnection(host, port, timeout=5)
        conn.request('GET', '/put_endpoint')
        response = conn.getresponse()
        assert response.status == HTTPStatus.METHOD_NOT_ALLOWED
        assert response.getheader('Allow') == 'PUT'
        assert response.getheader('Content-Length') == '0'
        response.read()
        conn.close()


def test_custom_put_handler() -> None:
    def custom_put_handler(_req: HttpRequest) -> Response:
        return Response('CUSTOM', content_type='text/plain')

    with _http(routers=[('PUT', '/upload', custom_put_handler)]) as server:
        host, port = _host_port(server)
        conn = HTTPConnection(host, port, timeout=5)
        conn.request('PUT', '/upload', body=b'abc', headers={'Content-Length': '3'})
        response = conn.getresponse()
        assert response.status == 200
        assert response.getheader('Content-Type') == 'text/plain'
        assert response.read() == b'CUSTOM'
        conn.close()


def test_default_put_handler() -> None:
    req = HttpRequest(method='PUT', path='/put_endpoint', received=10, content_length=10, truncated=False)
    result = default_put_handler(req)
    assert result.status == 200
    assert result.content_type == 'application/json'
    body = result.body_bytes()
    assert json.loads(body.decode())['received'] == 10


def test_https_requires_certfile_and_keyfile() -> None:
    with pytest.raises(ServerStartupError, match='certfile/keyfile or ssl_context'):
        HttpsHelper('127.0.0.1', 0)


def test_https_requires_both_certfile_and_keyfile(tmp_path: Path) -> None:
    (tmp_path / 'server.crt').write_text('test', encoding='utf-8')
    with pytest.raises(ServerStartupError, match='certfile/keyfile or ssl_context'):
        HttpsHelper('127.0.0.1', 0, certfile=str(tmp_path / 'server.crt'))


def test_post_endpoint_json() -> None:
    with _http() as server:
        host, port = _host_port(server)
        conn = HTTPConnection(host, port, timeout=5)
        conn.request('POST', '/post_endpoint', body=b'Q' * 32, headers={'Content-Length': '32'})
        response = conn.getresponse()
        assert response.status == 200
        assert json.loads(response.read().decode()) == {
            'received': 32,
            'truncated': False,
            'content_length': 32,
            'path': '/post_endpoint',
        }
        conn.close()


def test_delete_endpoint_json() -> None:
    with _http() as server:
        host, port = _host_port(server)
        conn = HTTPConnection(host, port, timeout=5)
        conn.request('DELETE', '/delete_endpoint')
        response = conn.getresponse()
        assert response.status == 200
        assert json.loads(response.read().decode()) == {'deleted': True, 'path': '/delete_endpoint'}
        conn.close()


def test_delete_large_body_returns_413() -> None:
    with _http(config=ServerConfig(max_put_payload=64)) as server:
        host, port = _host_port(server)
        conn = HTTPConnection(host, port, timeout=5)
        conn.request('DELETE', '/delete_endpoint', body=b'x' * 128, headers={'Content-Length': '128'})
        response = conn.getresponse()
        assert response.status == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        response.read()
        conn.close()


def test_put_large_body_returns_413() -> None:
    with _http(config=ServerConfig(max_put_payload=64)) as server:
        host, port = _host_port(server)
        conn = HTTPConnection(host, port, timeout=5)
        conn.request('PUT', '/put_endpoint', body=b'x' * 128, headers={'Content-Length': '128'})
        response = conn.getresponse()
        assert response.status == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        assert json.loads(response.read().decode()) == {
            'received': 64,
            'truncated': True,
            'content_length': 128,
        }
        conn.close()


def test_dynamic_route_update() -> None:
    routers = list(DEFAULT_ROUTERS)
    with _http(routers=routers) as server:
        host, port = _host_port(server)
        routers.append(('POST', '/dynamic_post', default_post_handler))
        conn = HTTPConnection(host, port, timeout=5)
        conn.request('POST', '/dynamic_post', body=b'hi', headers={'Content-Length': '2'})
        response = conn.getresponse()
        assert response.status == 200
        assert json.loads(response.read().decode())['received'] == 2
        conn.close()


def test_get_static_and_generated() -> None:
    with _http() as server:
        host, port = _host_port(server)
        conn = HTTPConnection(host, port, timeout=5)
        conn.request('GET', '/get_bytes_1k')
        response = conn.getresponse()
        body = response.read()
        assert response.status == 200
        assert body == b'A' * 1024

        conn.request('GET', '/get_bytes_2k')
        response = conn.getresponse()
        generated = response.read()
        assert response.status == 200
        assert generated == b'A' * 2048

        conn.request('GET', '/get_bytes?size=512')
        response = conn.getresponse()
        queried = response.read()
        assert response.status == 200
        assert queried == b'A' * 512

        conn.request('GET', '/get_text_2k')
        response = conn.getresponse()
        assert response.status == 200
        assert response.getheader('Content-Type') == 'text/plain'
        assert response.read() == b'A' * 2048

        conn.request('GET', '/get_text?size=512')
        response = conn.getresponse()
        assert response.status == 200
        assert response.getheader('Content-Type') == 'text/plain'
        assert response.read() == b'A' * 512
        conn.close()


def test_head_static_has_no_body() -> None:
    with _http() as server:
        host, port = _host_port(server)
        conn = HTTPConnection(host, port, timeout=5)
        conn.request('HEAD', '/get_bytes_1k')
        response = conn.getresponse()
        assert response.status == 200
        assert response.getheader('Content-Length') == '1024'
        assert response.read() == b''
        conn.close()


def test_response_status_and_content_type() -> None:
    def handler(_req: HttpRequest) -> Response:
        return Response('{"ok": true}', status=201, content_type='application/json')

    with _http(routers=[('GET', '/meta', handler)]) as server:
        host, port = _host_port(server)
        conn = HTTPConnection(host, port, timeout=5)
        conn.request('GET', '/meta')
        response = conn.getresponse()
        assert response.status == 201
        assert response.getheader('Content-Type') == 'application/json'
        assert response.read() == b'{"ok": true}'
        conn.close()


def test_http_server_context_manager() -> None:
    with _http() as server:
        host, port = _host_port(server)
        conn = HTTPConnection(host, port, timeout=5)
        conn.request('GET', '/check_get_endpoint')
        response = conn.getresponse()
        assert response.status == 200
        assert response.getheader('Content-Type') == 'text/plain; charset=utf-8'
        assert response.read() == b'OK'
        conn.close()


def test_https_get_with_user_certs(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    _write_self_signed_certs(tmp_path)
    with caplog.at_level(logging.INFO, logger='esptest.http_helper'):
        with HttpsHelper(
            '127.0.0.1',
            0,
            routers=list(DEFAULT_ROUTERS),
            certfile=str(tmp_path / 'server.crt'),
            keyfile=str(tmp_path / 'server.key'),
        ) as server:
            host, port = server.address
            assert f'server started (https://{host}:{port}/list_routers)' in caplog.text
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            conn = HTTPSConnection(host, port, context=ctx, timeout=5)
            conn.request('GET', '/check_get_endpoint')
            response = conn.getresponse()
            assert response.status == 200
            assert response.read() == b'OK'
            conn.close()


def test_https_mutual_tls(tmp_path: Path) -> None:
    _write_mtls_certs(tmp_path)
    with HttpsHelper(
        '127.0.0.1',
        0,
        routers=list(DEFAULT_ROUTERS),
        certfile=str(tmp_path / 'server.crt'),
        keyfile=str(tmp_path / 'server.key'),
        cafile=str(tmp_path / 'ca.crt'),
    ) as server:
        host, port = server.address
        client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        client.check_hostname = False
        client.verify_mode = ssl.CERT_REQUIRED
        client.load_verify_locations(cafile=str(tmp_path / 'ca.crt'))
        client.load_cert_chain(certfile=str(tmp_path / 'client.crt'), keyfile=str(tmp_path / 'client.key'))
        conn = HTTPSConnection(host, port, context=client, timeout=5)
        conn.request('GET', '/check_get_endpoint')
        response = conn.getresponse()
        assert response.status == 200
        assert response.read() == b'OK'
        conn.close()

        anonymous = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        anonymous.check_hostname = False
        anonymous.verify_mode = ssl.CERT_NONE
        rejected = HTTPSConnection(host, port, context=anonymous, timeout=5)
        # A missing client certificate is a TLS alert or a peer reset, depending on OpenSSL.
        with pytest.raises((ssl.SSLError, ConnectionResetError)):
            rejected.request('GET', '/check_get_endpoint')
            rejected.getresponse()
