# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/) (0.x: a minor release may break the API).

## [0.14.0] - Unreleased

A redesign as a standalone, side-effect-free package. Every breaking change is listed under **Removed** and **Changed**; [MIGRATION.md](MIGRATION.md) shows the replacement code for each.

### Security

- **OIDC audience enforcement.** With `OIDC_AUDIENCE` configured:
  - tokens without an `aud` claim are now rejected;
  - every configured audience is accepted, not only the first.

  Before, an access token issued for any client of the same provider passed. A GitHub security advisory covers this fix.
- **Token verification errors.**
  - The 401 answers no longer echo exception text to unauthenticated callers.
  - Server errors during verification are no longer reported as 401.
- **API keys.** `get_api_key_verifier` now rejects expired keys (`expires_at` in the past). It also rejects keys that are not UUIDs, without a database query.
- **Correlation IDs.** An incoming `X-Correlation-ID` is used only when it matches `[A-Za-z0-9._:-]{1,64}`. Unbounded client input no longer reaches logs and responses.
- **Client IP.** The client IP taken from `X-Forwarded-For` is validated as an IP address, so arbitrary header text no longer reaches log records.
- **Algorithms.** Only asymmetric JWS algorithms can be configured; `HS*` and `none` are refused.

### Removed

- **Action required:** Python 3.14 support. `requires-python` is now `>=3.15`.
- **Action required:** the `handle_exceptions` decorator. Built-in exceptions are no longer translated, so `ValueError`, `LookupError`, `PermissionError`, `ConnectionRefusedError` and `NotImplementedError` now give a 500 unless the app handles them. Raise the new `ServiceError` subclasses and call `register_exception_handlers(app)`.
- **Action required:** the `fastapi_commons.conf` module (`ApiAuthSettings`, `api_auth_settings`, `oidc_settings`) and the `API_AUTH_ENABLED` variable. Use `get_token_verifier(..., required=False)` for optional authentication and `app.dependency_overrides` in tests.
- **Action required:** the module globals `auth.oidc_client`, `auth.oidc_settings` and `auth.bearer_security`. The OIDC client now comes from `oidc_lifespan`.
- **Action required:** `SHARED_LOG_CONFIG`, and the `EndpointFilter` that was attached to `uvicorn.access` at import. Add `fastapi_commons.log.filters.EndpointFilter` to your own logging configuration.
- `setup_opentelemetry` is no longer re-exported from `fastapi_commons`. Import it from `fastapi_commons.instrumentation`.
- The `OTLP_GRPC_ENDPOINT` variable, its `http://tempo:4317` default, and the `compose_service` resource attribute.
- `PrometheusMiddleware.get_path` and `dist_name`.
- The direct dependencies on python-jose, email-validator (`pydantic[email]`), asyncpg and pydantic. They were never imported, or they come with python3-commons. An app that uses `jose` or `EmailStr` must declare those packages itself.

### Changed

- **Action required:** token verification needs `oidc_lifespan(app, settings)` in the application lifespan; without it, protected requests get 500.
  - The lifespan creates one `OIDCClient` per application and closes it on shutdown.
  - It fails at startup when `OIDC_AUTHORITY_URL` is missing. `OIDC_CLIENT_ID` is no longer needed.
- **Action required:** with no `OIDC_AUDIENCE` configured, tokens that carry `aud` are now accepted. Before, they were rejected.
- **Action required:** OpenTelemetry moved behind the `otel` extra (`fastapi-commons[otel]`).
  - `setup_opentelemetry(app, *, service_name=None, log_correlation=True)` replaces `setup_opentelemetry(app, app_name)`.
  - It reads the standard `OTEL_*` variables and no longer changes the logging format.
- **Action required:** `get_client_ip(request, x_forwarded_for)` becomes `get_client_ip(connection)`. It returns the leftmost valid `X-Forwarded-For` entry or the TCP peer. `LogContextMiddleware` now uses it, so the logged IP is the forwarded one.
- **Action required:** `get_api_key_verifier(session_dependency, *, header_name='X-API-Key')`. The default header was `Api-Key`, and `header_name` is now keyword-only.
- Token verification errors:
  - 401 `Token is invalid` or `Token has expired`, with `WWW-Authenticate: Bearer error="invalid_token"`;
  - 401 `Not authenticated` without credentials;
  - 503 when the provider or JWKS cannot be reached.
- JWT verification uses PyJWT.
- `correlation_id_ctx` lives in `fastapi_commons.context` and defaults to `None`. Before, `.get()` raised `LookupError` outside a request.
- The middleware is pure ASGI instead of `BaseHTTPMiddleware`. `add_middleware` usage is unchanged.
- Prometheus:
  - requests that match no route are now recorded with the path label `<unmatched>`;
  - `/docs`, `/redoc` and `/openapi.json` are not recorded by default;
  - durations include streamed response bodies;
  - failed requests are timed too.
- Dependencies use floors with major caps instead of `~=` pins.

### Added

- `oidc_lifespan`, `get_oidc` and `OIDCState`.
- `get_token_verifier(token_cls, *, required=True, algorithms=('RS256',))`:
  - typed overloads (`required=False` returns `T | None`);
  - signing-key selection by `kid`, with a JWKS refresh on an unknown `kid` (key rotation);
  - support for RS, PS, ES and EdDSA algorithms.
- The `fastapi_commons.exceptions` classes: `ServiceError`, `BadRequestError`, `UnauthorizedError`, `ForbiddenError`, `NotFoundError`, `ConflictError` and `UnavailableError`.
- `register_exception_handlers(app)` and `UnhandledErrorMiddleware`.
- `fastapi_commons.context` with `get_correlation_id()`.
- Log filters:
  - `CorrelationIDFilter` and `LogContextFilter` take a `default`, so formats work outside requests;
  - `EndpointFilter(paths=...)` works with any server's access logger.
- `PrometheusMiddleware(..., excluded_paths=...)`.
- Every public name is re-exported lazily from `fastapi_commons`. Every module declares `__all__`, and the package ships `py.typed`.

### Fixed

- `OIDCClient` was built at import from optional settings. That failed type checking with python3-commons 0.30, and the client's session was reopened on every request.
- An unknown signing key ID caused 401s until the JWKS cache expired.
- A non-RSA key listed before the signing key could break verification.
- Prometheus:
  - exception causes were stripped (`raise e from None`);
  - `CancelledError` was counted as an exception;
  - an all-zero `TraceID` exemplar was attached without an active span;
  - the route templates relied on FastAPI's private `_IncludedRouter`.
- The log filters raised on formats that used their fields outside a request, and `LogContextFilter` wrote the context variable from inside logging.
- `setup_opentelemetry` was not idempotent, and it changed the global logging configuration.

## Earlier releases

Releases before 0.14.0 have no entries here; see the git history and the tags.
