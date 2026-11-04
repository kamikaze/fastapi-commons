import logging
from http import HTTPStatus
from typing import Annotated

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from python3_commons.exceptions import AppError

from fastapi_commons.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceError,
    UnauthorizedError,
    UnavailableError,
)
from fastapi_commons.handlers import register_exception_handlers

SECRET = 'secret-internal-message'


class TeapotError(ServiceError):
    status_code = HTTPStatus.IM_A_TEAPOT


def _client(app: FastAPI, *, raise_app_exceptions: bool = True) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions), base_url='http://test'
    )


def _make_app(exc: BaseException) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get('/boom')
    async def boom() -> None:
        raise exc

    return app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('exc', 'status'),
    [
        (BadRequestError('bad'), 400),
        (UnauthorizedError('bad'), 401),
        (ForbiddenError('bad'), 403),
        (NotFoundError('bad'), 404),
        (ConflictError('bad'), 409),
        (TeapotError('bad'), 418),
    ],
)
async def test_client_errors(exc: ServiceError, status: int) -> None:
    async with _client(_make_app(exc)) as client:
        response = await client.get('/boom')

    assert response.status_code == status
    assert response.json() == {'detail': 'bad'}


@pytest.mark.asyncio
async def test_default_detail_is_status_phrase() -> None:
    async with _client(_make_app(NotFoundError())) as client:
        response = await client.get('/boom')

    assert response.json() == {'detail': 'Not Found'}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('exc', 'status'),
    [
        (ServiceError(SECRET), 500),
        (UnavailableError(SECRET), 503),
        (AppError(SECRET), 500),
    ],
)
async def test_server_errors_are_generic(exc: AppError, status: int) -> None:
    async with _client(_make_app(exc)) as client:
        response = await client.get('/boom')

    assert response.status_code == status
    assert SECRET not in response.text
    assert response.json() == {'detail': HTTPStatus(status).phrase}


@pytest.mark.asyncio
async def test_headers_passthrough() -> None:
    app = _make_app(UnauthorizedError('no', headers={'WWW-Authenticate': 'Bearer'}))

    async with _client(app) as client:
        response = await client.get('/boom')

    assert response.status_code == 401
    assert response.headers['www-authenticate'] == 'Bearer'


@pytest.mark.asyncio
async def test_error_in_dependency_is_mapped() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    async def dep() -> None:
        raise NotFoundError('missing')

    @app.get('/x')
    async def endpoint(_: Annotated[None, Depends(dep)]) -> None:
        return None

    async with _client(app) as client:
        response = await client.get('/x')

    assert response.status_code == 404
    assert response.json() == {'detail': 'missing'}


@pytest.mark.asyncio
async def test_builtins_not_mapped() -> None:
    async with _client(_make_app(ValueError('x')), raise_app_exceptions=False) as client:
        response = await client.get('/boom')

    assert response.status_code == 500
    assert 'detail' not in response.text

    with pytest.raises(ValueError, match='x'):
        async with _client(_make_app(ValueError('x'))) as client:
            await client.get('/boom')


@pytest.mark.asyncio
async def test_existing_handler_is_kept() -> None:
    app = FastAPI()

    @app.exception_handler(ServiceError)
    async def custom(_request: object, _exc: Exception) -> JSONResponse:
        return JSONResponse({'custom': True}, status_code=499)

    register_exception_handlers(app)

    @app.get('/boom')
    async def boom() -> None:
        raise NotFoundError('x')

    async with _client(app) as client:
        response = await client.get('/boom')

    assert response.status_code == 499
    assert response.json() == {'custom': True}


@pytest.mark.asyncio
async def test_client_error_logged_as_warning_without_traceback(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger='fastapi_commons.handlers'):
        async with _client(_make_app(NotFoundError('gone'))) as client:
            await client.get('/boom')

    records = [r for r in caplog.records if r.name == 'fastapi_commons.handlers']

    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].exc_info is None
    message = records[0].getMessage()
    assert 'GET' in message
    assert '/boom' in message
    assert '404' in message
    assert 'NotFoundError' in message
    assert 'gone' in message


@pytest.mark.asyncio
@pytest.mark.parametrize('exc', [ServiceError(SECRET), UnavailableError(SECRET), AppError(SECRET)])
async def test_server_error_logged_with_traceback(exc: AppError, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger='fastapi_commons.handlers'):
        async with _client(_make_app(exc)) as client:
            await client.get('/boom')

    records = [r for r in caplog.records if r.name == 'fastapi_commons.handlers']

    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert records[0].exc_info is not None
    assert isinstance(records[0].exc_info, tuple)
    assert records[0].exc_info[1] is exc
