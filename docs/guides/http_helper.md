# HTTP/HTTPS test helper

`esptest.tools.http_helper` starts a local threaded HTTP or HTTPS server for
DUT and integration tests. It wraps the stdlib
{class}`http.server.ThreadingHTTPServer`.

## Core vs optional

**Core** — what you always use:

- {class}`~esptest.tools.http_helper.HttpHelper` / {class}`~esptest.tools.http_helper.HttpsHelper`
- a `with` block (`serve_forever` blocks, so the helper runs it in a thread)
- INFO log `server started (http://<host>:<port>)` (or `https://`) when the serve thread starts
- `address` → `(host, port)` after bind (`port=0` picks an ephemeral port)
- `routers=[]` by default; `GET /` lists supported routers as `text/plain`, other unknown paths return 404
- responses are HTTP/1.0, so the connection closes after each response

**Optional** — only when the default is not enough:

| Piece | When to touch it |
| --- | --- |
| `routers` / `DEFAULT_ROUTERS` | Custom `(method, path, handler)` tuples, or the ESP fixture |
| `/get_bytes_1k` / `/get_bytes?size=<n>` / `/get_bytes_<n>` | GET body of ``n`` ``A`` bytes |
| `/get_text?size=<n>` / `/get_text_<n>` | GET body of ``n`` ``A`` characters, ``text/plain`` |
| {class}`~esptest.tools.http_helper.ServerConfig` | Host/port, payload caps, chunk size, timeouts |
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
    cafile='/path/to/ca.crt',  # optional
) as https:
    host, port = https.address
```

`cafile` is optional. When set, the server requires a client certificate signed by
that CA (`ssl.CERT_REQUIRED`). Omit it to skip client-certificate checks. You can
also pass a ready `ssl.SSLContext` as `ssl_context`. The handshake runs on the
accepted connection, so a TCP connection that never sends a ClientHello does not
block leaving the `with` block. A server closed by `with` cannot be entered again.

## Custom routers

A router is `HttpRouter = (method, path, handler)`. `method` may be any HTTP
method. DELETE, GET, HEAD, POST, and PUT are built in; any other method on a
router is dispatched the same way, and `Allow` lists only methods that have a
router. `path` is an exact `str`, or a compiled regex (`re.compile(...)`). The
handler receives {class}`~esptest.tools.http_helper.HttpRequest` (`method`,
`path` without the query, `query`, `raw_path`, plus `received` /
`content_length` / `truncated` after the body is drained). Matched methods fill
those counters and then discard the bytes. The handler returns
{class}`~esptest.tools.http_helper.Response` (`body` as `bytes` or `str`,
`status`, `content_type`). A `str` body defaults to `text/plain; charset=utf-8`;
a `bytes` body defaults to `application/octet-stream`. HEAD omits the body. A `HEAD`
router matches before the GET fallback, whichever was registered first.

```python
from esptest.tools.http_helper import HttpHelper, Response

def on_put(_req):
    return Response('CUSTOM', content_type='text/plain')

routers = [
    ('GET', '/', lambda req: Response('home')),  # replaces the default supported-routers page
    ('GET', '/invalid_url', lambda req: Response(status=404)),
    ('GET', '/hello', lambda req: Response('hello')),
    ('PUT', '/upload', on_put),
]

with HttpHelper('127.0.0.1', 0, routers=routers) as http:
    ...
```

The list is read on every request, so you can `append` a router on a running
server. `GET /` lists supported routers when no router is registered for `/`.
Register `('GET', '/', handler)` to replace that page, as in the example above.

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

`GET /` lists supported routers (`text/plain`) when no router is registered for `/`.
Other unknown paths return 404. A known path with the wrong method
returns 405, an `Allow` header, and `Connection: close`. 404, 405, and matched
GET/HEAD requests discard a request body (up to `max_put_payload`) so it is not
parsed as the next request. Generated `/get_bytes` and `/get_text` bodies
larger than `ServerConfig.max_get_payload` return 400 with an empty body.
PUT, POST, and DELETE bodies larger than `ServerConfig.max_put_payload` are
truncated and answered with 413 JSON `{received, truncated, content_length}`
(POST and DELETE also include `path`). Only `max_put_payload` bytes are read
before that response. A peer still sending the rest can see a connection reset
instead of the 413.
`truncated` means the declared body exceeded that cap. A disconnect or
`put_read_timeout` still returns 200 with `truncated` false and `received`
less than `content_length`, and the connection is closed. The connection is
also closed when the body is larger than `max_put_payload`, or when the
request uses `Transfer-Encoding: chunked` (that body is not read).
`ServerConfig.put_read_timeout` (default 10 seconds) limits each body read, not
the whole upload. It also bounds how long a connection may wait for a request
line, and how long the TLS handshake may take. `ServerConfig.thread_join_timeout`
(default 10 seconds) is how long leaving the `with` block waits for the serve
thread. `ServerConfig.write_timeout` limits each response write, including 404,
405, and 500 (default 600 seconds). A peer that stops reading releases the
handler thread when that timer expires, instead of waiting for the TCP
retransmit timeout. A write that does not finish closes the connection. A
`Content-Length` that is not a non-negative integer closes the connection so
the following bytes are not the next request.
