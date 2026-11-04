from http import HTTPStatus

import pytest
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


@pytest.mark.parametrize(
    ('cls', 'status'),
    [
        (ServiceError, HTTPStatus.INTERNAL_SERVER_ERROR),
        (BadRequestError, HTTPStatus.BAD_REQUEST),
        (UnauthorizedError, HTTPStatus.UNAUTHORIZED),
        (ForbiddenError, HTTPStatus.FORBIDDEN),
        (NotFoundError, HTTPStatus.NOT_FOUND),
        (ConflictError, HTTPStatus.CONFLICT),
        (UnavailableError, HTTPStatus.SERVICE_UNAVAILABLE),
    ],
)
def test_status_codes(cls: type[ServiceError], status: HTTPStatus) -> None:
    assert cls.status_code == status
    assert issubclass(cls, AppError)


def test_detail_and_headers_stored() -> None:
    headers = {'WWW-Authenticate': 'Bearer'}
    exc = UnauthorizedError('nope', headers=headers)
    headers['X'] = 'y'

    assert exc.detail == 'nope'
    assert exc.headers == {'WWW-Authenticate': 'Bearer'}
    assert str(exc) == 'nope'


def test_defaults() -> None:
    exc = NotFoundError()

    assert exc.detail is None
    assert exc.headers is None
    assert str(exc) == ''
    assert exc.args == ()


def test_subclass_keeps_parent_status() -> None:
    class OrderNotFoundError(NotFoundError):
        pass

    assert OrderNotFoundError.status_code == HTTPStatus.NOT_FOUND


def test_custom_status_subclass() -> None:
    class TeapotError(ServiceError):
        status_code = HTTPStatus.IM_A_TEAPOT

    assert TeapotError('x').status_code == HTTPStatus.IM_A_TEAPOT
