# fastapi-commons

Reusable building blocks for [FastAPI](https://fastapi.tiangolo.com/) applications:

- **Authentication:** OIDC bearer tokens verified against the provider's JWKS (PyJWT), and database-backed API keys.
- **Errors:** exception classes that carry their HTTP status, app-level exception handlers, and a JSON 500 for anything unhandled.
- **Request context:** correlation IDs, client IP and log filters that put both into every log record.
- **Metrics:** a Prometheus middleware labelled by route template, and the `/metrics` endpoint.
- **Tracing:** OpenTelemetry setup, with the `otel` extra.

Everything is a separate piece that the application wires itself. Importing the package has no side effects: no settings are read, no clients are created, and no logger is changed.

Requires Python 3.15.

## Installation

```bash
uv add fastapi-commons            # or: pip install fastapi-commons
uv add 'fastapi-commons[otel]'    # with OpenTelemetry tracing
```

## Wiring an application

```python
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from python3_commons.auth import TokenData
from python3_commons.conf import OIDCSettings

from fastapi_commons import (
    CorrelationIDMiddleware,
    LogContextMiddleware,
    NotFoundError,
    PrometheusMiddleware,
    UnhandledErrorMiddleware,
    get_token_verifier,
    metrics,
    oidc_lifespan,
    register_exception_handlers,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    async with oidc_lifespan(app, OIDCSettings()):
        yield


app = FastAPI(lifespan=lifespan)
register_exception_handlers(app)

# add_middleware puts each new middleware outside the previous ones: the last one added runs first.
app.add_middleware(PrometheusMiddleware, app_name='orders')
app.add_middleware(UnhandledErrorMiddleware)
app.add_middleware(LogContextMiddleware)
app.add_middleware(CorrelationIDMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=['https://app.example.com'], expose_headers=['X-Correlation-ID'])
app.add_route('/metrics', metrics, include_in_schema=False)

verify = get_token_verifier(TokenData)


class OrderNotFoundError(NotFoundError):
    pass


@app.get('/orders/{order_id}')
async def get_order(order_id: int, token: Annotated[TokenData, Depends(verify)]) -> dict[str, int]:
    raise OrderNotFoundError(f'order {order_id} does not exist')
```

The middleware order matters:

1. **CORS** is outermost, so every response, including a 500, carries the CORS headers.
2. **CorrelationIDMiddleware** sets the correlation ID before anything logs.
3. **LogContextMiddleware** records the client IP for the log filters.
4. **UnhandledErrorMiddleware** turns an unhandled exception into `{"detail": "Internal Server Error"}`. Because it sits inside the first three, that 500 still has their headers.
5. **PrometheusMiddleware** is innermost, so it sees the exception, counts it and times the request including streamed bodies.

## Authentication

### OIDC bearer tokens

`oidc_lifespan(app, settings)` creates one `OIDCClient` (from python3-commons) for the application:
- it keeps the client on `app.state` while the lifespan runs;
- it closes the client on shutdown;
- it fails at startup when `OIDC_AUTHORITY_URL` is missing.

`get_token_verifier(token_cls)` returns a FastAPI dependency that verifies the bearer token and returns its claims as `token_cls`, a `TokenData` subclass.

| Situation | Result |
|---|---|
| No credentials | 401 `Not authenticated`; with `required=False` the dependency returns `None` instead |
| Invalid, wrongly signed or wrong-audience token | 401 `Token is invalid`, `WWW-Authenticate: Bearer error="invalid_token"` |
| Expired token | 401 `Token has expired` |
| Provider or JWKS unreachable | 503 `OIDC provider is not available` |
| `oidc_lifespan` not running | 500 |

How tokens are checked:
- **Signing key:** selected by the token's `kid`. An unknown `kid` refreshes the JWKS once, which handles key rotation.
- **Algorithms:** only asymmetric ones are accepted, `algorithms=('RS256',)` by default; `HS*` and `none` are refused when the verifier is created.
- **Audience:** checked only when `OIDC_AUDIENCE` is set. Then `aud` is required and any configured value is accepted. With no audience configured, `aud` is not checked.
- **Issuer:** checked only when `OIDC_ISSUER` is set.
- **Clock skew:** `OIDC_LEEWAY` seconds are allowed.

```python
verify = get_token_verifier(TokenData)                           # -> TokenData
verify_optional = get_token_verifier(TokenData, required=False)  # -> TokenData | None

# In tests, skip the provider altogether:
app.dependency_overrides[verify] = lambda: TokenData(exp=0, iat=0, iss='test', sub='alice')
```

The verifier reads the client from the application that serves the request (`request.app.state`), so a mounted sub-application must run its own `oidc_lifespan`.

### API keys

`get_api_key_verifier(session_dependency, header_name='X-API-Key')` returns a dependency that looks the key up in python3-commons' `api_keys` table:
- a key that is not a UUID is rejected without a query;
- an expired key (`expires_at` in the past) is rejected;
- `session_dependency` may return the `AsyncSession` or yield it.

The key is the row's primary key, so it is stored in plaintext.

## Errors

Raise a `ServiceError` subclass and `register_exception_handlers(app)` answers with its status and `{"detail": ...}`:

| Class | Status |
|---|---|
| `BadRequestError` | 400 |
| `UnauthorizedError` | 401 |
| `ForbiddenError` | 403 |
| `NotFoundError` | 404 |
| `ConflictError` | 409 |
| `UnavailableError` | 503 |
| `ServiceError`, or any other `AppError` | 500 |

How these are answered:
- A 4xx sends the exception's detail and is logged as one WARNING line.
- A 5xx sends only the status phrase and is logged at ERROR with the traceback.
- `headers=` are passed through, for example `UnauthorizedError('...', headers={'WWW-Authenticate': 'Bearer'})`.
- Errors raised in dependencies are handled too.
- Handlers the application registered itself for these types are left alone.

Built-in exceptions (`ValueError`, `LookupError`, ...) are not translated: an unexpected one is a 500, not a 400 or 404.

## Request context and logging

- **`CorrelationIDMiddleware`:**
  - An incoming `X-Correlation-ID` is accepted when it matches `[A-Za-z0-9._:-]{1,64}`; otherwise a UUID is generated.
  - The ID is set on the response and is readable anywhere through `get_correlation_id()`.
  - `fastapi_commons.context` holds the context variables. It imports nothing from FastAPI, so workers can use it too.
- **`LogContextMiddleware`:** puts the client IP into the log context.
- **`get_client_ip(connection)`:**
  - Returns the leftmost `X-Forwarded-For` entry when it is a valid IP address, otherwise the TCP peer.
  - The leftmost entry comes from the client. It can be trusted only when your edge proxy overwrites `X-Forwarded-For` and the application cannot be reached any other way.
  - The server may rewrite the peer itself. uvicorn's `--proxy-headers`, on by default for connections from `127.0.0.1`, replaces the peer from `X-Forwarded-For`, and the fallback then returns that address.

The log filters never fail outside a request: missing values render as `-`. Configure them in your own `dictConfig`:

```python
LOGGING = {
    'version': 1,
    'filters': {
        'correlation_id': {'()': 'fastapi_commons.log.filters.CorrelationIDFilter'},
        'log_context': {'()': 'fastapi_commons.log.filters.LogContextFilter'},
        'no_metrics': {'()': 'fastapi_commons.log.filters.EndpointFilter', 'paths': ['/metrics', '/health']},
    },
    'formatters': {
        'default': {'format': '%(asctime)s %(levelname)s [%(correlation_id)s] [%(client_ip)s] %(name)s: %(message)s'},
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'default',
            'filters': ['correlation_id', 'log_context'],
        },
    },
    'loggers': {
        # The access logger of your server (uvicorn.access, granian.access, ...). The servers set propagate=False
        # on it, so give it a handler here: an entry without one replaces the server's handler with nothing.
        'granian.access': {'handlers': ['console'], 'filters': ['no_metrics'], 'propagate': False},
    },
    'root': {'level': 'INFO', 'handlers': ['console']},
}
```

## Metrics

`PrometheusMiddleware(app, app_name='fastapi-app', excluded_paths=...)` records these metrics:
- `fastapi_requests_total`, `fastapi_responses_total` and `fastapi_requests_duration_seconds`;
- `fastapi_exceptions_total` and `fastapi_requests_in_progress`;
- `fastapi_app_info`.

How the labels and timings are set:
- **Labels:** the route template (`/orders/{order_id}`), including routers included with a prefix and mounted sub-applications. A request that matches no route gets the label `<unmatched>`, so the label count stays bounded.
- **Exclusions:** `/metrics`, `/docs`, `/redoc` and `/openapi.json` are not recorded by default.
- **Timing:** durations include streamed response bodies.
- **Exemplars:** a duration observation carries a `TraceID` exemplar when a sampled OpenTelemetry span is active.

The metrics live in the default registry and assume one worker per process.

## Tracing (`otel` extra)

```python
from fastapi_commons.instrumentation import setup_opentelemetry

setup_opentelemetry(app, service_name='orders')
```

What it does:
- **Exporter:** OTLP over gRPC, configured by the standard variables (`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`, `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES`).
- **Disabling:** `OTEL_SDK_DISABLED=true` turns it off.
- **Repeat calls:** it may be called more than once. The tracer provider is created once per process, or an SDK provider that is already installed is reused.
- **Logging:** with `log_correlation=True` (the default) log records get `otelTraceID`, `otelSpanID` and `otelServiceName`. Handlers and formats are left alone.

## Configuration

The library reads no environment variables itself. `OIDCSettings` (python3-commons) reads these:

| Variable | Default | Meaning |
|---|---|---|
| `OIDC_AUTHORITY_URL` | - | Provider URL; required by `oidc_lifespan` |
| `OIDC_AUTHORITY_INTERNAL_HOST` | - | Internal host that replaces the authority's host for server-side calls |
| `OIDC_CLIENT_ID` | - | Not needed for token verification |
| `OIDC_CLIENT_SECRET` | - | Not needed for token verification |
| `OIDC_AUDIENCE` | - | Accepted audiences, comma-separated; empty: `aud` not checked |
| `OIDC_ISSUER` | - | Expected `iss`; empty: not checked |
| `OIDC_LEEWAY` | `0` | Allowed clock skew for `exp` and `nbf`, seconds |
| `OIDC_JWKS_CACHE_TTL` | `300` | Seconds the JWKS is cached |
| `OIDC_JWKS_REFRESH_INTERVAL` | `60` | Minimum seconds between JWKS refreshes for unknown key IDs |
| `OIDC_TIMEOUT` | `10` | Provider request timeout, seconds |
| `OIDC_VERIFY_CERT` | `true` | Verify the provider's TLS certificate |

Tracing uses the standard `OTEL_*` variables.

## Development

```bash
uv sync --all-extras
uv run ruff format src tests && uv run ruff check src tests
uv run ty check --error-on-warning src tests
uv run pyright src tests
uv run pytest --cov
```

`pre-commit install` runs the same checks before each commit.

## Releasing

1. Set `version` in `pyproject.toml`, and give the release its dated section in `CHANGELOG.md` (with `MIGRATION.md` for breaking changes).
2. Merge to `master`.
3. Push a signed tag `vX.Y.Z`.

The release workflow then:
1. runs the checks;
2. builds the distributions and checks that their version equals the tag;
3. publishes to PyPI through Trusted Publishing;
4. creates the GitHub release.

## License

GPL-3.0-only. See [LICENSE](LICENSE) and [AUTHORS.md](AUTHORS.md).
