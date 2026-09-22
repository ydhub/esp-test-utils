import io
import json
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
    HttpRouter,
    HttpsHelper,
    ServerConfig,
    ServerStartupError,
    _HttpHandler,
    match_route,
)


def _host_port(server: HttpHelper) -> Tuple[str, int]:
    return server.address


def _http(routes: Optional[List[HttpRouter]] = None, config: Optional[ServerConfig] = None) -> HttpHelper:
    return HttpHelper('127.0.0.1', 0, routes=routes, config=config)


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


def _fake_handler(
    *,
    rfile: Optional[io.BytesIO] = None,
    wfile: Optional[MagicMock] = None,
    content_length: int = 0,
    config: Optional[ServerConfig] = None,
    connection: object = None,
) -> MagicMock:
    handler = MagicMock()
    handler.rfile = rfile
    handler.wfile = wfile
    handler.content_length = content_length
    handler.server_config = config or ServerConfig()
    handler.connection = connection
    return handler


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


def test_parse_get_bytes_path_units() -> None:
    assert HttpHelper.parse_get_bytes_path('/get_bytes_100') == 100
    assert HttpHelper.parse_get_bytes_path('/get_bytes_5k') == 5120
    assert HttpHelper.parse_get_bytes_path('/get_bytes_2M') == 2 * 1024 * 1024
    assert HttpHelper.parse_get_bytes_path('/put_endpoint') is None


def test_route_match_priority() -> None:
    routes = list(DEFAULT_ROUTERS)

    sized = match_route(routes, '/get_bytes_1k')
    assert sized is not None
    assert sized[0] == 'GET'
    assert sized[2](MagicMock(path='/get_bytes_1k')) == b'A' * 1024

    query = match_route(routes, '/get_bytes')
    assert query is not None
    assert query[2](MagicMock(path='/get_bytes?size=2k')) == b'A' * 2048

    sized_5k = match_route(routes, '/get_bytes_5k')
    assert sized_5k is not None
    assert sized_5k[2](MagicMock(path='/get_bytes_5k')) == b'A' * 5120

    hello = match_route(routes, '/hello')
    assert hello is not None
    assert hello[2](MagicMock(path='/hello')) == b'hello'

    long_path = '/get_with_very_long_url_' + 'x' * 32
    long_route = match_route(routes, long_path)
    assert long_route is not None
    assert long_route[2](MagicMock(path=long_path)) == b'OK' + str(len(long_path)).encode()

    assert match_route(routes, '/put_endpoint', 'GET') is None
    assert match_route(routes, '/put_endpoint', 'PUT') is not None
    assert match_route(routes, '/put_with_very_long_url_' + 'y' * 16, 'PUT') is not None
    assert match_route(routes, '/post_endpoint', 'POST') is not None
    assert match_route(routes, '/post_endpoint', 'GET') is None
    assert match_route(routes, '/delete_endpoint', 'DELETE') is not None
    assert match_route(routes, '/missing') is None


def test_drain_request_body_truncation() -> None:
    payload = b'x' * (ServerConfig.max_put_payload + 50)
    handler = _fake_handler(
        rfile=io.BytesIO(payload),
        content_length=len(payload),
        config=ServerConfig(max_put_payload=1024),
    )
    assert _HttpHandler._drain_body(handler) == 1024


def test_drain_request_body_connection_reset() -> None:
    class BrokenReader(io.BytesIO):
        def read(self, n: Optional[int] = -1) -> bytes:
            raise ConnectionResetError('reset')

    handler = _fake_handler(rfile=BrokenReader(b'abc'), content_length=3)
    assert _HttpHandler._drain_body(handler) == 0


def test_write_generated_body_disconnect() -> None:
    wfile = MagicMock()
    wfile.write.side_effect = BrokenPipeError('gone')
    assert _HttpHandler._write_generated_body(_fake_handler(wfile=wfile), 1024) == 0


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
        response.read()
        conn.close()


def test_custom_put_handler() -> None:
    def custom_put_handler(_req: object) -> bytes:
        return b'CUSTOM'

    with _http(routes=[('PUT', '/upload', custom_put_handler)]) as server:
        host, port = _host_port(server)
        conn = HTTPConnection(host, port, timeout=5)
        conn.request('PUT', '/upload', body=b'abc', headers={'Content-Length': '3'})
        response = conn.getresponse()
        assert response.status == 200
        assert response.read() == b'CUSTOM'
        conn.close()


def test_default_put_handler() -> None:
    req = MagicMock(received=10, content_length=10, truncated=False, path='/put_endpoint')
    status, body = HttpHelper.default_put_handler(req)
    assert status == 200
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


def test_dynamic_route_update() -> None:
    routes = list(DEFAULT_ROUTERS)
    with _http(routes=routes) as server:
        host, port = _host_port(server)
        routes.append(('POST', '/dynamic_post', HttpHelper.default_post_handler))
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


def test_http_server_context_manager() -> None:
    with _http() as server:
        host, port = _host_port(server)
        conn = HTTPConnection(host, port, timeout=5)
        conn.request('GET', '/check_get_endpoint')
        response = conn.getresponse()
        assert response.status == 200
        assert response.read() == b'OK'
        conn.close()


def test_https_get_with_user_certs(tmp_path: Path) -> None:
    _write_self_signed_certs(tmp_path)
    with HttpsHelper(
        '127.0.0.1',
        0,
        certfile=str(tmp_path / 'server.crt'),
        keyfile=str(tmp_path / 'server.key'),
        cafile=str(tmp_path / 'server_ca.crt'),
    ) as server:
        host, port = server.address
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        conn = HTTPSConnection(host, port, context=ctx, timeout=5)
        conn.request('GET', '/check_get_endpoint')
        response = conn.getresponse()
        assert response.status == 200
        assert response.read() == b'OK'
        conn.close()
