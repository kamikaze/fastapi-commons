"""
Reusable building blocks for FastAPI applications: OIDC and API-key authentication, error handlers, request context
middleware, log filters, Prometheus metrics and (with the ``otel`` extra) OpenTelemetry tracing.

Every public name is re-exported here with a PEP 810 lazy import, so ``import fastapi_commons`` loads nothing until a
name is used. ``setup_opentelemetry`` needs the ``otel`` extra and is imported from ``fastapi_commons.instrumentation``.
"""

import importlib.metadata

lazy from fastapi_commons.auth import OIDCState, get_api_key_verifier, get_oidc, get_token_verifier, oidc_lifespan
lazy from fastapi_commons.context import correlation_id_ctx, get_correlation_id, log_context
lazy from fastapi_commons.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceError,
    UnauthorizedError,
    UnavailableError,
)
lazy from fastapi_commons.handlers import register_exception_handlers
lazy from fastapi_commons.helpers import get_client_ip
lazy from fastapi_commons.log.filters import CorrelationIDFilter, EndpointFilter, LogContextFilter
lazy from fastapi_commons.middleware.correlation_id import CorrelationIDMiddleware
lazy from fastapi_commons.middleware.errors import UnhandledErrorMiddleware
lazy from fastapi_commons.middleware.log_context import LogContextMiddleware
lazy from fastapi_commons.middleware.prometheus import PrometheusMiddleware, metrics

try:
    __version__ = importlib.metadata.version('fastapi-commons')
except importlib.metadata.PackageNotFoundError:  # pragma: no cover - only when run from a source tree without metadata
    __version__ = 'unknown'

__all__ = [
    'BadRequestError',
    'ConflictError',
    'CorrelationIDFilter',
    'CorrelationIDMiddleware',
    'EndpointFilter',
    'ForbiddenError',
    'LogContextFilter',
    'LogContextMiddleware',
    'NotFoundError',
    'OIDCState',
    'PrometheusMiddleware',
    'ServiceError',
    'UnauthorizedError',
    'UnavailableError',
    'UnhandledErrorMiddleware',
    '__version__',
    'correlation_id_ctx',
    'get_api_key_verifier',
    'get_client_ip',
    'get_correlation_id',
    'get_oidc',
    'get_token_verifier',
    'log_context',
    'metrics',
    'oidc_lifespan',
    'register_exception_handlers',
]
