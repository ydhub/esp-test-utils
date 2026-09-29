# HTTP/HTTPS test helper

`esptest.tools.http_helper` starts a local threaded HTTP or HTTPS server for
DUT and integration tests. It wraps the stdlib
{class}`http.server.ThreadingHTTPServer`.

## Core vs optional

**Core** — what you always use:

- {class}`~esptest.tools.http_helper.HttpHelper` / {class}`~esptest.tools.http_helper.HttpsHelper`
- a `with` block (`serve_forever` blocks, so the helper runs it in a thread)
- INFO log `server started (http://<host>:<port>/list_routers)` (or `https://`) when the serve thread starts
- `address` → `(host, port)` after bind (`port=0` picks an ephemeral port)
- `routers=[]` by default; unknown paths, including `GET /`, return 404
- `GET /list_routers` lists the installed routers as `text/plain`

**Optional** — only when the default is not enough:

| Piece | When to touch it |
| --- | --- |
| `routers` / `DEFAULT_ROUTERS` | Custom `(method, path, handler)` tuples, or the ESP fixture |
| `/get_bytes_1k` / `/get_bytes?size=<n>` / `/get_bytes_<n>` | GET body of ``n`` ``A`` bytes |
| `/get_text?size=<n>` / `/get_text_<n>` | GET body of ``n`` ``A`` characters, ``text/plain`` |
| {class}`~esptest.tools.http_helper.ServerConfig` | Host/port, payload cap, chunk size, timeouts |
| TLS files | Required for `HttpsHelper` (`certfile`/`keyfile` or `ssl_context`) |
| PUT/POST/DELETE handlers | Custom JSON or status codes |

## HTTP

```python
from esptest.tools.http_helper import DEFAULT_ROUTERS, HttpHelper

with HttpHelper('127.0.0.1', 0, routers=list(DEFAULT_ROUTERS)) as http:
    host, port = http.address
    # GET /check_get_endpoint -> b'OK'
    # GET /get_bytes_1k      -> 1024 bytes of 'A'
    # PUT /put_endpoint      -> {"received": N, ...}
```

Default listen address is `ServerConfig.host:ServerConfig.http_port`
(`0.0.0.0:8000`). HTTPS uses `https_port` (`8443`). Use `port=0` in unit tests
to avoid collisions.

## HTTPS

HTTPS is a subclass of HTTP. Certificates are **not** bundled; pass them in:

```python
from esptest.tools.http_helper import HttpsHelper

with HttpsHelper(
    '127.0.0.1',
    0,
    certfile='/path/to/server.crt',
    keyfile='/path/to/server.key',
    cafile='/path/to/ca.crt',  # 可选
) as https:
    host, port = https.address
```

`cafile` is optional. When set, the server requires a client certificate signed by
that CA (`ssl.CERT_REQUIRED`). Omit it to skip client-certificate checks. You can
also pass a ready `ssl.SSLContext` as `ssl_context`.

## Custom routers

A router is `HttpRouter = (method, path, handler)`. `path` is an exact `str`,
or a compiled regex (`re.compile(...)`). The handler receives
{class}`~esptest.tools.http_helper.HttpRequest` (`method`, `path`, plus
`received` / `content_length` / `truncated` after the body is drained) and
returns {class}`~esptest.tools.http_helper.Response` (`body` as `bytes` or `str`,
`status`, `content_type`). A `str` body defaults to `text/plain; charset=utf-8`;
a `bytes` body defaults to `application/octet-stream`. HEAD reuses GET routers and
omits the body.

```python
from esptest.tools.http_helper import HttpHelper, Response

def on_put(_req):
    return Response('CUSTOM', content_type='text/plain')

routers = [
    ('GET', '/hello', lambda req: Response('hello')),
    ('PUT', '/upload', on_put),
]

with HttpHelper('127.0.0.1', 0, routers=routers) as http:
    ...
```

The list is read on every request, so you can `append` a router on a running
server.

## Default routers

`DEFAULT_ROUTERS` is the ESP HTTP test fixture. Pass
`routers=list(DEFAULT_ROUTERS)` to install it:

| Method | Path | Behavior | Content-Type |
| --- | --- | --- | --- |
| GET/HEAD | `/get_with_very_long_url_<any>` | `OK` plus the request URL length | `text/plain` |
| GET/HEAD | `/hello` | `hello` | `text/plain; charset=utf-8` |
| GET/HEAD | `/check_get_endpoint` | `OK` | `text/plain; charset=utf-8` |
| GET/HEAD | `/invalid_url` | empty body, status 404 | `application/octet-stream` |
| GET/HEAD | `/get_bytes_1k` | 1024 bytes of `A` | `application/octet-stream` |
| GET/HEAD | `/get_bytes?size=<n>[k\|m]` | `n` bytes of `A` | `application/octet-stream` |
| GET/HEAD | `/get_bytes_<n>[k\|m]` | `n` bytes of `A` (`k`/`m` suffixes) | `application/octet-stream` |
| GET/HEAD | `/get_text?size=<n>[k\|m]` | `n` characters of `A` | `text/plain` |
| GET/HEAD | `/get_text_<n>[k\|m]` | `n` characters of `A` (`k`/`m` suffixes) | `text/plain` |
| PUT | `/put_endpoint` | `{received, truncated, content_length}` | `application/json` |
| PUT | `/put_with_very_long_url_<any>` | same as `/put_endpoint` | `application/json` |
| POST | `/post_endpoint` | same JSON plus `path` | `application/json` |
| DELETE | `/delete_endpoint` | `{deleted, path}` | `application/json` |

`GET /` returns 404 unless a router is registered for it. `GET /list_routers` lists the
installed routers. Other unknown paths return 404. A known path with the wrong method
returns 405 and an `Allow` header. PUT, POST, and DELETE bodies larger than
`ServerConfig.max_put_payload` are truncated and answered with 413.
