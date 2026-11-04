import uuid
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import Annotated, Any, cast

import httpx
import pytest
from fastapi import Depends, FastAPI
from python3_commons.db.models.auth import ApiKey
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_commons.auth import get_api_key_verifier

KEY_ID = uuid.UUID('6a1f3e4c-2b7d-4c55-9e0a-3f1b2c4d5e6f')


class Result:
    def __init__(self, row: ApiKey | None) -> None:
        self.row = row

    def scalar_one_or_none(self) -> ApiKey | None:
        return self.row


class Session:
    """A stand-in for AsyncSession: answers every query with one row and records the statements."""

    def __init__(self, row: ApiKey | None) -> None:
        self.row = row
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> Result:
        self.statements.append(statement)

        return Result(self.row)


def key(*, expires_at: datetime | None = None) -> ApiKey:
    return ApiKey(uid=KEY_ID, name='service', expires_at=expires_at)


def returning(session: Session) -> Callable[[], AsyncSession]:
    def get_session() -> AsyncSession:
        return cast('AsyncSession', session)

    return get_session


def yielding(session: Session) -> Callable[[], AsyncGenerator[AsyncSession]]:
    async def get_session() -> AsyncGenerator[AsyncSession]:
        yield cast('AsyncSession', session)

    return get_session


def awaiting(session: Session) -> Callable[[], Any]:
    async def get_session() -> AsyncSession:
        return cast('AsyncSession', session)

    return get_session


def build_app(dependency: Callable[..., Any], **options: str) -> FastAPI:
    app = FastAPI()
    verify = get_api_key_verifier(dependency, **options)

    @app.get('/whoami')
    async def whoami(api_key: Annotated[ApiKey, Depends(verify)]) -> dict[str, str]:
        return {'name': api_key.name}

    return app


async def call(app: FastAPI, headers: dict[str, str] | None = None) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        return await client.get('/whoami', headers=headers)


@pytest.mark.asyncio
@pytest.mark.parametrize('make_dependency', [returning, yielding, awaiting])
@pytest.mark.parametrize(
    'expires_at',
    [None, datetime.now(UTC) + timedelta(hours=1), datetime.now() + timedelta(days=1)],  # naive: UTC
)
async def test_valid_key(make_dependency: Callable[[Session], Callable[..., Any]], expires_at: datetime | None) -> None:
    session = Session(key(expires_at=expires_at))
    response = await call(build_app(make_dependency(session)), {'X-API-Key': str(KEY_ID)})

    assert (response.status_code, response.json()) == (HTTPStatus.OK, {'name': 'service'})
    assert len(session.statements) == 1


@pytest.mark.asyncio
async def test_missing_key() -> None:
    session = Session(key())
    response = await call(build_app(returning(session)))

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json() == {'detail': 'Not authenticated'}
    assert response.headers['www-authenticate'] == 'APIKey'
    assert session.statements == []


@pytest.mark.asyncio
@pytest.mark.parametrize('value', ['not-a-uuid', "1' OR '1'='1", f'{KEY_ID}x'])
async def test_malformed_key_is_rejected_without_a_query(value: str) -> None:
    session = Session(key())
    response = await call(build_app(returning(session)), {'X-API-Key': value})

    assert (response.status_code, response.json()) == (HTTPStatus.UNAUTHORIZED, {'detail': 'Invalid API key'})
    assert response.headers['www-authenticate'] == 'APIKey'
    assert session.statements == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'row',
    [
        None,
        key(expires_at=datetime.now(UTC) - timedelta(seconds=1)),
        key(expires_at=datetime.now() - timedelta(days=1)),  # naive: read as UTC
    ],
)
async def test_unknown_or_expired_key(row: ApiKey | None) -> None:
    response = await call(build_app(returning(Session(row))), {'X-API-Key': str(KEY_ID)})

    assert (response.status_code, response.json()) == (HTTPStatus.UNAUTHORIZED, {'detail': 'Invalid API key'})


@pytest.mark.asyncio
async def test_query_uses_the_parsed_uuid() -> None:
    session = Session(key())
    await call(build_app(returning(session)), {'X-API-Key': str(KEY_ID).upper()})

    (statement,) = session.statements
    params = statement.compile().params

    assert list(params.values()) == [KEY_ID]


@pytest.mark.asyncio
async def test_custom_header() -> None:
    app = build_app(returning(Session(key())), header_name='Api-Key')

    assert (await call(app, {'Api-Key': str(KEY_ID)})).status_code == HTTPStatus.OK
    assert (await call(app, {'X-API-Key': str(KEY_ID)})).status_code == HTTPStatus.UNAUTHORIZED
