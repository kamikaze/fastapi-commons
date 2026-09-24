# fastapi-commons

Common utilities, middleware, security, and observability helpers for production-ready [FastAPI](https://fastapi.tiangolo.com/) microservices.

---

## Overview

`fastapi-commons` provides shared building blocks across FastAPI services to eliminate boilerplate. It integrates Prometheus metrics, OpenTelemetry distributed tracing, contextual logging with correlation IDs, OpenID Connect (OIDC) JWT and database API key authentication, and structured exception handling.

---

## Features

### 1. Observability & Prometheus Metrics
- **`PrometheusMiddleware`**: Tracks HTTP request counts, response statuses, in-progress requests, and request durations.
  - Automatically resolves parameterized route templates (e.g. `/items/{id}` instead of `/items/123`) to prevent metric cardinality explosion.
  - Supports OpenTelemetry trace exemplars on duration histograms to link metrics to traces.
- **`metrics`**: Pre-configured route handler exposing metrics in OpenMetrics / Prometheus exposition format.
- **Access log filtering**: Built-in `EndpointFilter` suppresses noisy `GET /metrics` access logs in Uvicorn.

### 2. Distributed Tracing (OpenTelemetry)
- **`setup_opentelemetry`**: One-line configuration for OpenTelemetry tracing.
  - Configures `TracerProvider`, `Resource` attributes, and `BatchSpanProcessor` with an OTLP gRPC exporter.
  - Instruments FastAPI endpoints and Python logging for trace correlation.

### 3. Correlation ID & Contextual Logging
- **`CorrelationIDMiddleware`**: Inspects or generates an `X-Correlation-ID` HTTP header, propagating it across request context and returning it in responses.
- **`LogContextMiddleware`**: Captures client information (such as client IP, respecting `X-Forwarded-For`).
- **`CorrelationIDFilter` & `LogContextFilter`**: Logging filters that inject correlation IDs and request context into Python log records.
- **`SHARED_LOG_CONFIG`**: Standard log format containing timestamps, log levels, logger names, trace IDs, span IDs, and service names.

### 4. Authentication & Authorization
- **OIDC Token Verification (`get_token_verifier`)**:
  - Validates Bearer JWT tokens against OpenID Connect (OIDC) JSON Web Key Sets (JWKS) via RS256.
  - Deserializes and validates token claims into custom models using `msgspec`.
  - Can be toggled via environment settings (`API_AUTH_ENABLED`).
- **Database API Key Verification (`get_api_key_verifier`)**:
  - FastAPI dependency for validating API keys from request headers against database records using SQLAlchemy async sessions.

### 5. Exception Handling
- **`@handle_exceptions`**: Decorator for endpoint functions and handlers that catches common application errors and maps them to standard HTTP exceptions:
  - `PermissionError` $\to$ `401 Unauthorized`
  - `LookupError` $\to$ `404 Not Found`
  - `ValueError` $\to$ `400 Bad Request`
  - `ConnectionRefusedError` $\to$ `503 Service Unavailable`
  - `NotImplementedError` $\to$ `501 Not Implemented`
  - `AppError` / `ValidationError` $\to$ `500 Internal Server Error`

---

## Installation

Using `uv` (recommended):

```bash
uv add fastapi-commons
```

Or using `pip`:

```bash
pip install fastapi-commons
```

---

## Usage Guide

### Metrics & OpenTelemetry Setup

```python
from fastapi import FastAPI
from fastapi_commons import PrometheusMiddleware, metrics, setup_opentelemetry

app = FastAPI(title="My Service")

# Setup OpenTelemetry tracing
setup_opentelemetry(app, app_name="my-service")

# Setup Prometheus metrics middleware and endpoint
app.add_middleware(PrometheusMiddleware, app_name="my-service")
app.add_route("/metrics", metrics)

@app.get("/items/{item_id}")
async def get_item(item_id: int):
    return {"item_id": item_id}
```

### Correlation ID & Logging

```python
import logging
from fastapi import FastAPI
from fastapi_commons.middleware.correlation_id import CorrelationIDMiddleware
from fastapi_commons.middleware.log_context import LogContextMiddleware
from fastapi_commons.log.filters import CorrelationIDFilter, LogContextFilter

app = FastAPI()

# Add middlewares
app.add_middleware(CorrelationIDMiddleware)
app.add_middleware(LogContextMiddleware)

# Attach filters to your log handlers
handler = logging.StreamHandler()
handler.addFilter(CorrelationIDFilter())
handler.addFilter(LogContextFilter())
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(correlation_id)s] [%(client_ip)s] %(message)s",
    handlers=[handler],
)
```

### OIDC Authentication

```python
from fastapi import Depends, FastAPI
from python3_commons.auth import TokenData
from fastapi_commons.auth import get_token_verifier

app = FastAPI()

class UserClaims(TokenData):
    sub: str
    email: str | None = None

verify_token = get_token_verifier(UserClaims)

@app.get("/protected")
async def protected_route(claims: UserClaims = Depends(verify_token)):
    return {"message": f"Hello, {claims.sub}!"}
```

### Exception Handling Decorator

```python
from fastapi import FastAPI
from fastapi_commons.handlers import handle_exceptions

app = FastAPI()

@app.get("/find/{item_id}")
@handle_exceptions
async def find_item(item_id: int):
    if item_id < 0:
        raise ValueError("Item ID must be positive")
    if item_id == 404:
        raise LookupError("Item not found")
    return {"item_id": item_id}
```

---

## Configuration

Settings can be customized via environment variables:

| Environment Variable | Default             | Description                                      |
|----------------------|---------------------|--------------------------------------------------|
| `API_AUTH_ENABLED`   | `true`              | Enable or disable API authentication enforcement |
| `OTLP_GRPC_ENDPOINT` | `http://tempo:4317` | OpenTelemetry gRPC collector endpoint            |
| `OIDC_AUTHORITY_URL` | -                   | OpenID Connect authority / issuer URL            |
| `OIDC_CLIENT_ID`     | -                   | OpenID Connect client ID                         |
| `OIDC_CLIENT_SECRET` | -                   | OpenID Connect client secret                     |
| `OIDC_AUDIENCE`      | -                   | Expected token audience                          |
| `OIDC_TIMEOUT`       | `10.0`              | OIDC HTTP request timeout (seconds)              |
| `OIDC_VERIFY_CERT`   | `true`              | Verify TLS certificates for OIDC requests        |

---

## License

This project is licensed under the GNU General Public License v3 (`GPL-3.0`). See [LICENSE](LICENSE) for details.

## Contributors

See [AUTHORS.md](AUTHORS.md).
