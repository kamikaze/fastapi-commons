import importlib.metadata
import logging

from fastapi_commons.instrumentation import setup_opentelemetry
from fastapi_commons.middleware import PrometheusMiddleware, metrics

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
