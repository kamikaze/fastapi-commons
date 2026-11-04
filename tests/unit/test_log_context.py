import httpx
import pytest
from fastapi import FastAPI

from fastapi_commons.context import log_context
from fastapi_commons.middleware.log_context import LogContextMiddleware


def make_client(peer: tuple[str, int] | None) -> httpx.AsyncClient:
    app = FastAPI()
    app.add_middleware(LogContextMiddleware)

    @app.get('/ctx')
    async def ctx() -> dict[str, str]:
        return dict(log_context.get() or {})

    transport = httpx.ASGITransport(app=app, client=peer) if peer else httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url='http://test')


@pytest.mark.asyncio
async def test_client_ip_from_forwarded_for() -> None:
    async with make_client(('1.2.3.4', 123)) as client:
        r = await client.get('/ctx', headers={'X-Forwarded-For': '5.6.7.8, 10.0.0.1'})
    assert r.json() == {'client_ip': '5.6.7.8'}
    assert log_context.get() is None


@pytest.mark.asyncio
async def test_client_ip_from_peer() -> None:
    async with make_client(('1.2.3.4', 123)) as client:
        r = await client.get('/ctx')
    assert r.json() == {'client_ip': '1.2.3.4'}
    assert log_context.get() is None


@pytest.mark.asyncio
async def test_invalid_forwarded_for_uses_peer() -> None:
    async with make_client(('1.2.3.4', 123)) as client:
        r = await client.get('/ctx', headers={'X-Forwarded-For': 'unknown'})
    assert r.json() == {'client_ip': '1.2.3.4'}
