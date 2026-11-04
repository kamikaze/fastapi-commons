import time
from collections.abc import Collection, Iterable, Sequence
from typing import Any

from fastapi.routing import RouteContext, iter_route_contexts
from prometheus_client import REGISTRY, Counter, Gauge, Histogram
from prometheus_client.openmetrics.exposition import CONTENT_TYPE_LATEST, generate_latest
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match, Mount
from starlette.types import ASGIApp, Message, Receive, Scope, Send

try:
    from opentelemetry import trace
except ImportError:  # OpenTelemetry is optional
    trace = None

__all__ = ['PrometheusMiddleware', 'metrics']

UNMATCHED_PATH = '<unmatched>'
DEFAULT_EXCLUDED_PATHS = ('/metrics', '/docs', '/docs/oauth2-redirect', '/redoc', '/openapi.json')

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


def _join(prefix: str, path: str) -> str:
    return f'{prefix}{path}' if path != '/' or not prefix else prefix


def _resolve_template(routes: Iterable[Any], scope: Scope) -> str | None:
    """Return the route template matching ``scope`` (first full match, else first partial), or None."""
    partial: tuple[Any, Scope] | None = None

    for context in iter_route_contexts(list(routes)):
        match, child_scope = context.matches(scope)

        if match is Match.FULL:
            return _template_of(context, scope, child_scope)

        if match is Match.PARTIAL and partial is None:
            partial = (context, child_scope)

    if partial is not None:
        return _template_of(partial[0], scope, partial[1])

    return None


def _template_of(context: RouteContext, scope: Scope, child_scope: Scope) -> str | None:
    path = context.path

    if path is None:
        return None

    if isinstance(context.original_route, Mount):
        inner_routes: Sequence[Any] = getattr(context.original_route, 'routes', None) or []

        if not inner_routes:
            return path or '/'

        inner = _resolve_template(inner_routes, {**scope, **child_scope})

        return None if inner is None else _join(path, inner)

    return path


def _valid_sampled_trace_id() -> str | None:
    if trace is None:
        return None

    span_context = trace.get_current_span().get_span_context()

    if not span_context.is_valid or not span_context.trace_flags.sampled:
        return None

    return trace.format_trace_id(span_context.trace_id)


class PrometheusMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        app_name: str = 'fastapi-app',
        *,
        excluded_paths: Collection[str] = DEFAULT_EXCLUDED_PATHS,
    ) -> None:
        self.app = app
        self.app_name = app_name
        self.excluded_paths = frozenset(excluded_paths)
        INFO.labels(app_name=app_name).set(1)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        template = self._get_path(scope)
        path = template or UNMATCHED_PATH

        if (template or scope['path']) in self.excluded_paths:
            await self.app(scope, receive, send)
            return

        labels = {'method': scope['method'], 'path': path, 'app_name': self.app_name}
        status_code: int | None = None

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code

            if message['type'] == 'http.response.start' and status_code is None:
                status_code = message['status']

            await send(message)

        REQUESTS.labels(**labels).inc()
        REQUESTS_IN_PROGRESS.labels(**labels).inc()
        before_time = time.perf_counter()

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as e:
            EXCEPTIONS.labels(exception_type=type(e).__name__, **labels).inc()
            raise
        finally:
            duration = time.perf_counter() - before_time
            trace_id = _valid_sampled_trace_id()
            exemplar = {'TraceID': trace_id} if trace_id else None
            REQUESTS_PROCESSING_TIME.labels(**labels).observe(duration, exemplar=exemplar)
            RESPONSES.labels(status_code=status_code if status_code is not None else 500, **labels).inc()
            REQUESTS_IN_PROGRESS.labels(**labels).dec()

    @staticmethod
    def _get_path(scope: Scope) -> str | None:
        app = scope.get('app')
        routes = getattr(app, 'routes', None)

        if not routes:
            return None

        return _resolve_template(routes, scope)


def metrics(_request: Request) -> Response:
    return Response(
        generate_latest(REGISTRY),
        headers={'Content-Type': CONTENT_TYPE_LATEST},
    )
