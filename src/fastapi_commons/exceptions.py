from collections.abc import Mapping
from http import HTTPStatus
from typing import ClassVar

from python3_commons.exceptions import AppError

__all__ = [
    'BadRequestError',
    'ConflictError',
    'ForbiddenError',
    'NotFoundError',
    'ServiceError',
    'UnauthorizedError',
    'UnavailableError',
]


class ServiceError(AppError):
    """Base class for errors that map to an HTTP status.

    Extend by subclassing a concrete error (``class OrderNotFound(NotFoundError)``) or by
    subclassing ``ServiceError`` and setting ``status_code`` on the subclass.
    """

    status_code: ClassVar[HTTPStatus] = HTTPStatus.INTERNAL_SERVER_ERROR

    def __init__(self, detail: str | None = None, *, headers: Mapping[str, str] | None = None) -> None:
        if detail is None:
            super().__init__()
        else:
            super().__init__(detail)

        self.detail = detail
        self.headers = dict(headers) if headers is not None else None


class BadRequestError(ServiceError):
    """400 Bad Request."""

    status_code = HTTPStatus.BAD_REQUEST


class UnauthorizedError(ServiceError):
    """401 Unauthorized."""

    status_code = HTTPStatus.UNAUTHORIZED


class ForbiddenError(ServiceError):
    """403 Forbidden."""

    status_code = HTTPStatus.FORBIDDEN


class NotFoundError(ServiceError):
    """404 Not Found."""

    status_code = HTTPStatus.NOT_FOUND


class ConflictError(ServiceError):
    """409 Conflict."""

    status_code = HTTPStatus.CONFLICT


class UnavailableError(ServiceError):
    """503 Service Unavailable."""

    status_code = HTTPStatus.SERVICE_UNAVAILABLE
