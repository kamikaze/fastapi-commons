import asyncio
import uuid
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.responses import StreamingResponse
from opentelemetry import trace
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags
from prometheus_client import REGISTRY
from prometheus_client.openmetrics.exposition import CONTENT_TYPE_LATEST
from prometheus_client.samples import Exemplar
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route
from starlette.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

from fastapi_commons.middleware.prometheus import PrometheusMiddleware, metrics

pytestmark = pytest.mark.asyncio

TRACE_ID = 0x0123456789ABCDEF0123456789ABCDEF


class Boom(Exception):  # noqa: N818
    pass


@pytest.fixture
def app_name() -> str:
    return f'app-{uuid.uuid4().hex}'


def value(name: str, app_name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, {'app_name': app_name, **labels}) or 0.0


def client(app: FastAPI, *, raise_app_exceptions: bool = True) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
    return httpx.AsyncClient(transport=transport, base_url='http://test')


def make_app(app_name: str, excluded_paths: Sequence[str] = ('/metrics',)) -> FastAPI:
    app = FastAPI()
    app.add_middleware(PrometheusMiddleware, app_name=app_name, excluded_paths=excluded_paths)
    return app


async def test_path_param_template(app_name: str) -> None:
    app = make_app(app_name)

    @app.get('/items/{item_id}')
    async def item(item_id: int) -> dict[str, int]:
        return {'id': item_id}

    async with client(app) as c:
        assert (await c.get('/items/1')).status_code == 200
        assert (await c.get('/items/2')).status_code == 200

    assert value('fastapi_requests_total', app_name, method='GET', path='/items/{item_id}') == 2
    assert value('fastapi_responses_total', app_name, method='GET', path='/items/{item_id}', status_code='200') == 2
    assert value('fastapi_requests_duration_seconds_count', app_name, method='GET', path='/items/{item_id}') == 2
    assert value('fastapi_requests_in_progress', app_name, method='GET', path='/items/{item_id}') == 0


async def test_nested_router_with_prefix(app_name: str) -> None:
    app = make_app(app_name)
    inner = APIRouter(prefix='/inner')
    outer = APIRouter(prefix='/outer')

    @inner.get('/things/{thing_id}')
    async def thing(thing_id: str) -> str:
        return thing_id

    outer.include_router(inner, prefix='/v1')
    app.include_router(outer, prefix='/api')

    async with client(app) as c:
        assert (await c.get('/api/outer/v1/inner/things/abc')).status_code == 200

    path = '/api/outer/v1/inner/things/{thing_id}'
    assert value('fastapi_requests_total', app_name, method='GET', path=path) == 1


async def test_mounted_fastapi_subapp(app_name: str) -> None:
    app = make_app(app_name)
    sub = FastAPI()

    @sub.get('/items/{item_id}')
    async def item(item_id: int) -> int:
        return item_id

    app.mount('/sub', sub)

    async with client(app) as c:
        assert (await c.get('/sub/items/5')).status_code == 200

    assert value('fastapi_requests_total', app_name, method='GET', path='/sub/items/{item_id}') == 1


async def test_static_mount_uses_mount_path(app_name: str, tmp_path: Path) -> None:
    (tmp_path / 'a.txt').write_text('hi')
    app = make_app(app_name)
    app.mount('/static', StaticFiles(directory=tmp_path))

    async with client(app) as c:
        assert (await c.get('/static/a.txt')).status_code == 200

    assert value('fastapi_requests_total', app_name, method='GET', path='/static') == 1


async def test_unmatched_uses_placeholder(app_name: str) -> None:
    app = make_app(app_name)

    async with client(app) as c:
        assert (await c.get('/nope/secret-123')).status_code == 404

    assert value('fastapi_requests_total', app_name, method='GET', path='<unmatched>') == 1
    assert value('fastapi_responses_total', app_name, method='GET', path='<unmatched>', status_code='404') == 1
    for metric in REGISTRY.collect():
        for sample in metric.samples:
            assert sample.labels.get('path') != '/nope/secret-123'


async def test_plain_starlette_route(app_name: str) -> None:
    app = make_app(app_name)

    async def plain(_request: Request) -> Response:
        return Response(status_code=204)

    app.router.routes.append(Route('/plain/{x}', endpoint=plain))

    async with client(app) as c:
        await c.get('/plain/1')

    assert value('fastapi_requests_total', app_name, method='GET', path='/plain/{x}') == 1


async def test_method_not_allowed(app_name: str) -> None:
    app = make_app(app_name)

    @app.get('/only-get/{x}')
    async def only_get(x: str) -> str:
        return x

    async with client(app) as c:
        assert (await c.post('/only-get/1')).status_code == 405

    path = '/only-get/{x}'
    assert value('fastapi_responses_total', app_name, method='POST', path=path, status_code='405') == 1


async def test_excluded_paths_not_recorded(app_name: str) -> None:
    app = make_app(app_name, excluded_paths=['/skip', '/ghost'])

    @app.get('/skip')
    async def skip() -> str:
        return 'x'

    async with client(app) as c:
        assert (await c.get('/skip')).status_code == 200
        assert (await c.get('/ghost')).status_code == 404

    for metric in REGISTRY.collect():
        for sample in metric.samples:
            assert sample.labels.get('app_name') != app_name or metric.name == 'fastapi_app_info'


async def test_exception_counted_and_propagated(app_name: str) -> None:
    app = make_app(app_name)
    cause = ValueError('root')

    @app.get('/boom')
    async def boom() -> None:
        raise Boom('bad') from cause

    async with client(app) as c:
        with pytest.raises(Boom) as exc_info:
            await c.get('/boom')

    assert exc_info.value.__cause__ is cause
    labels = {'method': 'GET', 'path': '/boom'}
    assert value('fastapi_exceptions_total', app_name, exception_type='Boom', **labels) == 1
    assert value('fastapi_responses_total', app_name, status_code='500', **labels) == 1
    assert value('fastapi_requests_in_progress', app_name, **labels) == 0
    assert value('fastapi_requests_duration_seconds_count', app_name, **labels) == 1


async def test_cancelled_error_not_counted(app_name: str) -> None:
    async def hang(_scope: Scope, _receive: Receive, _send: Send) -> None:
        raise asyncio.CancelledError

    mw = PrometheusMiddleware(hang, app_name=app_name)
    app = make_app(app_name)
    scope = {'type': 'http', 'method': 'GET', 'path': '/x', 'app': app}

    async def receive() -> dict[str, str]:
        return {}

    async def send(_message: object) -> None:
        return None

    with pytest.raises(asyncio.CancelledError):
        await mw(scope, receive, send)

    assert REGISTRY.get_sample_value('fastapi_exceptions_total', {'app_name': app_name}) is None
    assert value('fastapi_requests_in_progress', app_name, method='GET', path='<unmatched>') == 0


async def test_streaming_duration_includes_body(app_name: str) -> None:
    app = make_app(app_name)

    @app.get('/stream')
    async def stream() -> StreamingResponse:
        async def gen() -> AsyncIterator[bytes]:
            for _ in range(3):
                await asyncio.sleep(0.05)
                yield b'x'

        return StreamingResponse(gen())

    async with client(app) as c:
        assert (await c.get('/stream')).content == b'xxx'

    total = value('fastapi_requests_duration_seconds_sum', app_name, method='GET', path='/stream')
    assert total >= 0.15


async def test_info_set_to_one_for_multiple_instances(app_name: str) -> None:
    async def noop(_scope: Scope, _receive: Receive, _send: Send) -> None:
        return None

    PrometheusMiddleware(noop, app_name=app_name)
    PrometheusMiddleware(noop, app_name=app_name)

    assert REGISTRY.get_sample_value('fastapi_app_info', {'app_name': app_name}) == 1.0


def exemplars(app_name: str) -> list[Exemplar]:
    return [
        s.exemplar
        for m in REGISTRY.collect()
        for s in m.samples
        if s.labels.get('app_name') == app_name and s.exemplar is not None
    ]


def span(flags: int) -> NonRecordingSpan:
    return NonRecordingSpan(SpanContext(TRACE_ID, 0x0123456789ABCDEF, is_remote=False, trace_flags=TraceFlags(flags)))


async def get_ok(app_name: str) -> None:
    app = make_app(app_name)

    @app.get('/ok')
    async def ok() -> str:
        return 'ok'

    async with client(app) as c:
        await c.get('/ok')


async def test_exemplar_with_sampled_span(app_name: str) -> None:
    with trace.use_span(span(TraceFlags.SAMPLED)):
        await get_ok(app_name)

    found = exemplars(app_name)
    assert len(found) == 1
    assert found[0].labels == {'TraceID': '0123456789abcdef0123456789abcdef'}


async def test_no_exemplar_without_span(app_name: str) -> None:
    await get_ok(app_name)
    assert exemplars(app_name) == []


async def test_no_exemplar_with_unsampled_span(app_name: str) -> None:
    with trace.use_span(span(TraceFlags.DEFAULT)):
        await get_ok(app_name)
    assert exemplars(app_name) == []


async def test_metrics_endpoint_content_type(app_name: str) -> None:
    app = make_app(app_name)
    app.add_route('/metrics', metrics)

    async with client(app) as c:
        response = await c.get('/metrics')

    assert response.headers['content-type'] == CONTENT_TYPE_LATEST
    assert 'fastapi_app_info' in response.text
    assert value('fastapi_requests_total', app_name, method='GET', path='/metrics') == 0


async def test_non_http_scopes_pass_through(app_name: str) -> None:
    seen: list[str] = []

    async def inner(scope: Scope, _receive: Receive, _send: Send) -> None:
        seen.append(scope['type'])

    mw = PrometheusMiddleware(inner, app_name=app_name)

    async def receive() -> dict[str, str]:
        return {}

    async def send(_message: object) -> None:
        return None

    await mw({'type': 'websocket'}, receive, send)
    await mw({'type': 'lifespan'}, receive, send)

    assert seen == ['websocket', 'lifespan']
