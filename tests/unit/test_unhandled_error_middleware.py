import logging
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fastapi_commons.exceptions import NotFoundError, UnavailableError
from fastapi_commons.middleware.errors import UnhandledErrorMiddleware


class RaisingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] == 'http':
            raise NotFoundError('from middleware')

        await self.app(scope, receive, send)


def _client(app: FastAPI, *, raise_app_exceptions: bool = False) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions), base_url='http://test'
    )


def _app() -> FastAPI:
    app = FastAPI()

    @app.get('/boom')
    async def boom() -> None:
        msg = 'kaboom'
        raise RuntimeError(msg)

    @app.get('/unavailable')
    async def unavailable() -> None:
        raise UnavailableError('secret')

    @app.get('/stream')
    async def stream() -> StreamingResponse:
        async def gen() -> AsyncIterator[bytes]:
            yield b'a'
            msg = 'mid-stream'
            raise RuntimeError(msg)

        return StreamingResponse(gen())

    return app


@pytest.mark.asyncio
async def test_unhandled_error_returns_json_500() -> None:
    app = _app()
    app.add_middleware(UnhandledErrorMiddleware)

    async with _client(app, raise_app_exceptions=True) as client:
        response = await client.get('/boom')

    assert response.status_code == 500
    assert response.json() == {'detail': 'Internal Server Error'}
    assert 'kaboom' not in response.text


@pytest.mark.asyncio
async def test_500_carries_cors_headers() -> None:
    app = _app()
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=['*'])

    async with _client(app) as client:
        response = await client.get('/boom', headers={'Origin': 'http://example.com'})

    assert response.status_code == 500
    assert response.headers['access-control-allow-origin'] == '*'


@pytest.mark.asyncio
async def test_logged_once_with_traceback(caplog: pytest.LogCaptureFixture) -> None:
    app = _app()
    app.add_middleware(UnhandledErrorMiddleware)

    with caplog.at_level(logging.DEBUG):
        async with _client(app) as client:
            await client.get('/boom')

    records = [r for r in caplog.records if r.levelno >= logging.ERROR]

    assert len(records) == 1
    assert records[0].exc_info is not None
    assert isinstance(records[0].exc_info, tuple)
    assert isinstance(records[0].exc_info[1], RuntimeError)


@pytest.mark.asyncio
async def test_service_error_from_inner_middleware() -> None:
    app = _app()
    app.add_middleware(RaisingMiddleware)
    app.add_middleware(UnhandledErrorMiddleware)

    async with _client(app, raise_app_exceptions=True) as client:
        response = await client.get('/boom')

    assert response.status_code == 404
    assert response.json() == {'detail': 'from middleware'}


@pytest.mark.asyncio
async def test_server_service_error_is_generic() -> None:
    # Without registered handlers the ServiceError reaches the middleware.
    app = _app()
    app.add_middleware(UnhandledErrorMiddleware)

    async with _client(app, raise_app_exceptions=True) as client:
        response = await client.get('/unavailable')

    assert response.status_code == 503
    assert response.json() == {'detail': 'Service Unavailable'}


@pytest.mark.asyncio
async def test_error_after_response_started_is_reraised(caplog: pytest.LogCaptureFixture) -> None:
    app = _app()
    app.add_middleware(UnhandledErrorMiddleware)

    with caplog.at_level(logging.DEBUG), pytest.raises(RuntimeError, match='mid-stream'):
        async with _client(app, raise_app_exceptions=True) as client:
            await client.get('/stream')

    assert any(r.exc_info is not None for r in caplog.records)


@pytest.mark.asyncio
async def test_lifespan_scope_passes_through() -> None:
    seen: list[str] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope['type'])
        await receive()
        await send({'type': 'lifespan.startup.complete'})

    sent: list[Message] = []

    async def receive() -> Message:
        return {'type': 'lifespan.startup'}

    async def send(message: Message) -> None:
        sent.append(message)

    await UnhandledErrorMiddleware(inner)({'type': 'lifespan'}, receive, send)

    assert seen == ['lifespan']
    assert sent == [{'type': 'lifespan.startup.complete'}]
