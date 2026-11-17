# Migrating from 0.12 to 0.13

0.13.0 is a redesign. Every section below is one breaking change; [CHANGELOG.md](CHANGELOG.md) lists them all.

## Python 3.15

`requires-python` is now `>=3.15`. Move the application to Python 3.15 first.

## OIDC token verification

The OIDC client is no longer a module global built at import. Enter `oidc_lifespan` from the application's lifespan:

```python
# before
from fastapi_commons.auth import get_token_verifier

app = FastAPI()
verify = get_token_verifier(TokenData)
```

```python
# after
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from python3_commons.conf import OIDCSettings

from fastapi_commons import get_token_verifier, oidc_lifespan


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    async with oidc_lifespan(app, OIDCSettings()):
        yield


app = FastAPI(lifespan=lifespan)
verify = get_token_verifier(TokenData)
```

Without the lifespan, protected endpoints answer 500. `oidc_lifespan` fails at startup when `OIDC_AUTHORITY_URL` is missing, and `OIDC_CLIENT_ID` is no longer needed.

Also check:

- **Audience.** When `OIDC_AUDIENCE` is set, tokens must carry a matching `aud`; tokens without `aud` are now rejected. When it is not set, `aud` is no longer checked (before, tokens with `aud` were rejected).
- **Statuses and texts.**
  - Invalid tokens get 401 `Token is invalid`, and expired ones 401 `Token has expired`, with `WWW-Authenticate: Bearer error="invalid_token"`.
  - An unreachable provider gives 503.
  - Clients that matched the old detail texts must be updated.
- **Algorithms.** `algorithms=` accepts asymmetric algorithms only, with a default of `RS256`.

## `API_AUTH_ENABLED` and `fastapi_commons.conf`

`fastapi_commons.conf` and the global switch are gone.

| Before | After |
|---|---|
| `API_AUTH_ENABLED=false`, so a route sees `None` | `get_token_verifier(TokenData, required=False)` returns `None` only when no credentials are sent |
| Tests set `api_auth_settings.enabled = False` | `app.dependency_overrides[verify] = lambda: TokenData(...)` |
| Tests patch `auth.oidc_client.get_jwks` or `auth.oidc_settings` | Override the verifier dependency, or pass your own settings to `oidc_lifespan` |
| `from fastapi_commons.conf import oidc_settings` | Build `OIDCSettings()` yourself and pass it to `oidc_lifespan` |
| `auth.bearer_security` | Not needed: the verifier declares its own `HTTPBearer` scheme |

## `handle_exceptions`

The decorator is removed, and built-in exceptions are no longer translated to statuses. Raise status-carrying exceptions and register the handlers once:

```python
# before
@app.get('/items/{item_id}')
@handle_exceptions
async def get_item(item_id: int) -> Item:
    raise LookupError(f'item {item_id} not found')  # -> 404
```

```python
# after
from fastapi_commons import NotFoundError, register_exception_handlers

register_exception_handlers(app)


class ItemNotFoundError(NotFoundError):
    pass


@app.get('/items/{item_id}')
async def get_item(item_id: int) -> Item:
    raise ItemNotFoundError(f'item {item_id} not found')  # -> 404 {"detail": "item 1 not found"}
```

| Before (built-in) | After |
|---|---|
| `ValueError` → 400 | `BadRequestError` |
| `PermissionError` → 401 | `UnauthorizedError`, or `ForbiddenError` for 403 |
| `LookupError` → 404 | `NotFoundError` |
| `ConnectionRefusedError` → 503 | `UnavailableError` |
| `NotImplementedError` → 501 | a `ServiceError` subclass with `status_code = HTTPStatus.NOT_IMPLEMENTED` |
| `AppError`, `ValidationError` → 500 | unchanged for `AppError` (500 with a generic detail) |

What else changes:
- Code that still raises built-ins now produces a 500, so catch them at the boundary and re-raise a `ServiceError`.
- A 5xx no longer sends the exception text.
- Errors raised inside dependencies are now handled as well.
- Add `UnhandledErrorMiddleware` to get a JSON 500 that carries CORS and correlation headers; the README shows the middleware order.

## Logging

`SHARED_LOG_CONFIG` is removed. Nothing is attached to `uvicorn.access` at import any more. Put the filters into your own logging configuration:

```python
'filters': {
    'correlation_id': {'()': 'fastapi_commons.log.filters.CorrelationIDFilter'},
    'log_context': {'()': 'fastapi_commons.log.filters.LogContextFilter'},
    'no_metrics': {'()': 'fastapi_commons.log.filters.EndpointFilter', 'paths': ['/metrics']},
},
'loggers': {
    # or granian.access; the server sets propagate=False, so name a handler or the access log goes silent
    'uvicorn.access': {'handlers': ['console'], 'filters': ['no_metrics'], 'propagate': False},
},
```

Outside a request, both filters now fill in `-` instead of leaving the attribute missing.

## Correlation ID context

```python
# before
from fastapi_commons.middleware.correlation_id import correlation_id_ctx

correlation_id_ctx.get()  # LookupError outside a request
```

```python
# after
from fastapi_commons import get_correlation_id

get_correlation_id()  # None outside a request
```

`correlation_id_ctx` and `log_context` now live in `fastapi_commons.context`, which imports nothing from FastAPI. An incoming `X-Correlation-ID` that doesn't match `[A-Za-z0-9._:-]{1,64}` is replaced by a generated UUID.

## Client IP

`get_client_ip(request, x_forwarded_for)` became `get_client_ip(connection)`. It returns the leftmost `X-Forwarded-For` entry when it is a valid IP address, otherwise the TCP peer. `LogContextMiddleware` uses the same function, so logs now show the forwarded address. Trust the forwarded address only when your edge proxy overwrites `X-Forwarded-For`.

## API keys

```python
# before
verify_key = get_api_key_verifier(get_session, 'Api-Key')
```

```python
# after
verify_key = get_api_key_verifier(get_session, header_name='Api-Key')  # the default is now X-API-Key
```

- Keys that are not UUIDs, and keys whose `expires_at` has passed, now get 401.
- The challenge header is `WWW-Authenticate: APIKey`.
- `get_session` may now also be an async generator dependency.

## OpenTelemetry

```bash
uv add 'fastapi-commons[otel]'
```

```python
# before
from fastapi_commons import setup_opentelemetry

setup_opentelemetry(app, 'orders')  # endpoint from OTLP_GRPC_ENDPOINT, default http://tempo:4317
```

```python
# after
from fastapi_commons.instrumentation import setup_opentelemetry

setup_opentelemetry(app, service_name='orders')  # endpoint from OTEL_EXPORTER_OTLP_ENDPOINT
```

Then:
- Replace `OTLP_GRPC_ENDPOINT` with `OTEL_EXPORTER_OTLP_ENDPOINT` (or `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`). There is no `tempo` default any more.
- `setup_opentelemetry` no longer changes the logging format. Add `%(otelTraceID)s` / `%(otelSpanID)s` to your own format if you want them.
- The `compose_service` resource attribute is gone.

## Prometheus

- **Labels:** requests that match no route are now counted under `path="<unmatched>"`.
- **Exclusions:** `/docs`, `/redoc` and `/openapi.json` are excluded by default; use `excluded_paths=` to change that.
- **Timing:** durations now include streamed bodies, so dashboards may show longer times for streaming endpoints.
- **Removed:** `PrometheusMiddleware.get_path`.

## Dependencies no longer installed

python-jose, email-validator, asyncpg (it still comes with python3-commons' `database` extra) and the OTel packages (now in the `otel` extra). Declare them yourself if your application imports them directly, for example `jose`, or `EmailStr`, which needs email-validator.
