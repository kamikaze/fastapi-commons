import importlib
import importlib.metadata
import logging
from typing import TYPE_CHECKING

from fastapi_commons.middleware.prometheus import PrometheusMiddleware, metrics

if TYPE_CHECKING:
    from fastapi_commons.instrumentation import setup_opentelemetry

try:
    dist_name = __name__
    __version__ = importlib.metadata.version(dist_name)
except importlib.metadata.PackageNotFoundError:
    __version__ = 'unknown'

__all__ = ['PrometheusMiddleware', 'metrics', 'setup_opentelemetry']

SHARED_LOG_CONFIG = (
    '%(asctime)s %(levelname)s [%(name)s] [%(filename)s:%(lineno)d] [trace_id=%(otelTraceID)s '
    'span_id=%(otelSpanID)s resource.service.name=%(otelServiceName)s] - %(message)s'
)


class EndpointFilter(logging.Filter):
    # Uvicorn endpoint access log filter
    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage().find('GET /metrics') == -1


# Filter out /endpoint
logging.getLogger('uvicorn.access').addFilter(EndpointFilter())


def __getattr__(name: str) -> object:
    """
    setup_opentelemetry is imported on first access: its OpenTelemetry SDK and OTLP gRPC exporter (~30 MB) are not
    loaded by services that use only other parts of the package
    """
    if name == 'setup_opentelemetry':
        return importlib.import_module('fastapi_commons.instrumentation').setup_opentelemetry

    msg = f'module {__name__!r} has no attribute {name!r}'

    raise AttributeError(msg)
