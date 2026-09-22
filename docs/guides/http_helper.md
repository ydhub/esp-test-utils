# HTTP/HTTPS test helper

`esptest.tools.http_helper` starts a local threaded HTTP or HTTPS server for
DUT and integration tests. It wraps the stdlib
{class}`http.server.ThreadingHTTPServer`.

## Core vs optional

**Core** — what you always use:

- {class}`~esptest.tools.http_helper.HttpHelper` / {class}`~esptest.tools.http_helper.HttpsHelper`
- a `with` block (`serve_forever` blocks, so the helper runs it in a thread)
- `address` → `(host, port)` after bind (`port=0` picks an ephemeral port)

**Optional** — only when the default is not enough:

| Piece | When to touch it |
| --- | --- |
| `routes` / `DEFAULT_ROUTERS` | Custom `(method, path, handler)` tuples |
| `/get_bytes_1k` / `/get_bytes?size=<n>` / `/get_bytes_<n>` | GET body of ``n`` ``A`` bytes |
| {class}`~esptest.tools.http_helper.ServerConfig` | Host/port, payload cap, chunk size, timeouts |
| TLS files | Required for `HttpsHelper` (`certfile`/`keyfile` or `ssl_context`) |
| PUT/POST/DELETE handlers | Custom JSON or status codes |

## HTTP

```python
from esptest.tools.http_helper import HttpHelper

with HttpHelper('127.0.0.1', 0) as http:
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

`cafile` is optional. You can also pass a ready `ssl.SSLContext` as `ssl_context`.

## Custom routes

A route is `HttpRouter = (method, path, handler)`. `path` is an exact string,
or a regex when it starts with `^`. The handler receives the stdlib request
(`command`, `path`, plus `received` / `content_length` / `truncated` after the
body is drained) and returns `bytes`, a generated size (`int`),
`(status, body)`, or `None` (404). HEAD reuses GET routes and omits the body.

```python
from esptest.tools.http_helper import HttpHelper

def on_put(_req):
    return b'CUSTOM'

routes = [
    ('GET', '/hello', lambda req: b'hello'),
    ('PUT', '/upload', on_put),
]

with HttpHelper('127.0.0.1', 0, routes=routes) as http:
    ...
```

The list is read on every request, so you can `append` a route on a running
server.

## Default routes

`DEFAULT_ROUTERS` registers:

| Method | Path | Behavior |
| --- | --- | --- |
| GET/HEAD | `/get_with_very_long_url_<any>` | `OK` plus the request URL length |
| GET/HEAD | `/hello` | `hello` |
| GET/HEAD | `/check_get_endpoint` | `OK` |
| GET/HEAD | `/get_bytes_1k` | 1024 bytes of `A` |
| GET/HEAD | `/get_bytes?size=<n>[k\|m]` | `n` bytes of `A` |
| GET/HEAD | `/get_bytes_<n>[k\|m]` | `n` bytes of `A` (`k`/`m` suffixes) |
| PUT | `/put_endpoint` | JSON `{received, truncated, content_length}` |
| PUT | `/put_with_very_long_url_<any>` | same as `/put_endpoint` |
| POST | `/post_endpoint` | same JSON plus `path` |
| DELETE | `/delete_endpoint` | JSON `{deleted, path}` |

Unknown paths return 404. A known path with the wrong method returns 405 and
an `Allow` header. PUT/POST/DELETE bodies larger than
`ServerConfig.max_put_payload` are truncated (DELETE answers 413).
