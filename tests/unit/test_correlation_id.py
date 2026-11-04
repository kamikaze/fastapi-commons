import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from fastapi_commons.context import correlation_id_ctx, get_correlation_id
from fastapi_commons.middleware.correlation_id import CorrelationIDMiddleware


@pytest.fixture
def client() -> httpx.AsyncClient:
    app = FastAPI()
    app.add_middleware(CorrelationIDMiddleware)

    @app.get('/id')
    async def read_id() -> dict[str, str | None]:
        return {'id': get_correlation_id()}

    @app.get('/boom')
    async def boom() -> None:
        raise HTTPException(status_code=418)

    @app.get('/stream')
    async def stream() -> StreamingResponse:
        async def gen() -> AsyncIterator[bytes]:
            yield b'a'
            yield b'b'

        return StreamingResponse(gen())

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test')


@pytest.mark.asyncio
async def test_valid_incoming_is_echoed(client: httpx.AsyncClient) -> None:
    async with client:
        r = await client.get('/id', headers={'X-Correlation-ID': 'abc-1.2_3:4'})
    assert r.headers['X-Correlation-ID'] == 'abc-1.2_3:4'
    assert r.json() == {'id': 'abc-1.2_3:4'}
    assert correlation_id_ctx.get() is None


@pytest.mark.asyncio
@pytest.mark.parametrize('value', [None, '', 'a' * 65, 'bad value', 'a/b', 'a,b'])
async def test_missing_or_invalid_is_replaced(client: httpx.AsyncClient, value: str | None) -> None:
    headers = {} if value is None else {'X-Correlation-ID': value}
    async with client:
        r = await client.get('/id', headers=headers)
    cid = r.headers['X-Correlation-ID']
    assert str(uuid.UUID(cid, version=4)) == cid
    assert r.json() == {'id': cid}
    assert correlation_id_ctx.get() is None


@pytest.mark.asyncio
async def test_64_chars_accepted(client: httpx.AsyncClient) -> None:
    async with client:
        r = await client.get('/id', headers={'X-Correlation-ID': 'a' * 64})
    assert r.headers['X-Correlation-ID'] == 'a' * 64


@pytest.mark.asyncio
async def test_header_on_404_and_http_exception(client: httpx.AsyncClient) -> None:
    async with client:
        r404 = await client.get('/missing', headers={'X-Correlation-ID': 'x1'})
        r418 = await client.get('/boom', headers={'X-Correlation-ID': 'x2'})
    assert (r404.status_code, r404.headers['X-Correlation-ID']) == (404, 'x1')
    assert (r418.status_code, r418.headers['X-Correlation-ID']) == (418, 'x2')


@pytest.mark.asyncio
async def test_streaming_response_gets_header(client: httpx.AsyncClient) -> None:
    async with client:
        r = await client.get('/stream', headers={'X-Correlation-ID': 'x3'})
    assert r.content == b'ab'
    assert r.headers['X-Correlation-ID'] == 'x3'
    assert correlation_id_ctx.get() is None
