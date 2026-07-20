import time
from collections.abc import Sequence

from fastapi.routing import APIRoute, _IncludedRouter
from opentelemetry import trace
from prometheus_client import REGISTRY, Counter, Gauge, Histogram
from prometheus_client.openmetrics.exposition import (
    CONTENT_TYPE_LATEST,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import BaseRoute, Match, Mount
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR
from starlette.types import ASGIApp, Scope

INFO = Gauge('fastapi_app_info', 'FastAPI application information.', ['app_name'])
REQUESTS = Counter(
    'fastapi_requests_total',
    'Total count of requests by method and path.',
    ['method', 'path', 'app_name'],
)
RESPONSES = Counter(
    'fastapi_responses_total',
    'Total count of responses by method, path and status codes.',
    ['method', 'path', 'status_code', 'app_name'],
)
REQUESTS_PROCESSING_TIME = Histogram(
    'fastapi_requests_duration_seconds',
    'Histogram of requests processing time by path (in seconds)',
    ['method', 'path', 'app_name'],
)
EXCEPTIONS = Counter(
    'fastapi_exceptions_total',
    'Total count of exceptions raised by path and exception type',
    ['method', 'path', 'exception_type', 'app_name'],
)
REQUESTS_IN_PROGRESS = Gauge(
    'fastapi_requests_in_progress',
    'Gauge of requests by method and path currently being processed',
    ['method', 'path', 'app_name'],
)


def _join_paths(prefix: str, path: str) -> str:
    if not prefix:
        return path
    return f'{prefix.rstrip("/")}/{path.lstrip("/")}'


def _resolve_route_path(routes: Sequence[BaseRoute], scope: Scope) -> str | None:
    """Resolve the templated path of the route matching ``scope``."""
    for route in routes:
        match, _ = route.matches(scope)

        if match is not Match.FULL:
            continue

        if isinstance(route, _IncludedRouter):
            prefix = route.include_context.prefix or ''
            stripped_path = scope['path'][len(prefix) :]
            sub_scope = {**scope, 'path': stripped_path} if prefix else scope
            sub_path = _resolve_route_path(route.original_router.routes, sub_scope)

            if sub_path is not None:
                return _join_paths(prefix, sub_path)

            continue

        if isinstance(route, (APIRoute, Mount)):
            return route.path

    return None


class PrometheusMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, app_name: str = 'fastapi-app') -> None:
        super().__init__(app)
        self.app_name = app_name
        INFO.labels(app_name=self.app_name).inc()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        method = request.method
        path, is_handled_path = self.get_path(request)

        if not is_handled_path:
            return await call_next(request)

        labels = {
            'method': method,
            'path': path,
            'app_name': self.app_name,
        }

        REQUESTS_IN_PROGRESS.labels(**labels).inc()
        REQUESTS.labels(**labels).inc()
        before_time = time.perf_counter()
        status_code = HTTP_500_INTERNAL_SERVER_ERROR

        try:
            response = await call_next(request)
        except BaseException as e:
            EXCEPTIONS.labels(exception_type=type(e).__name__, **labels).inc()
            raise e from None
        else:
            status_code = response.status_code
            after_time = time.perf_counter()
            # Retrieve trace id for exemplar
            span = trace.get_current_span()
            trace_id = trace.format_trace_id(span.get_span_context().trace_id)

            REQUESTS_PROCESSING_TIME.labels(**labels).observe(after_time - before_time, exemplar={'TraceID': trace_id})
        finally:
            RESPONSES.labels(status_code=status_code, **labels).inc()
            REQUESTS_IN_PROGRESS.labels(**labels).dec()

        return response

    @staticmethod
    def get_path(request: Request) -> tuple[str, bool]:
        if path := _resolve_route_path(request.app.routes, request.scope):
            return path, True

        return request.url.path, False


def metrics(_request: Request) -> Response:
    return Response(
        generate_latest(REGISTRY),
        headers={'Content-Type': CONTENT_TYPE_LATEST},
    )
