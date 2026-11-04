import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from python3_commons.exceptions import AppError

from fastapi_commons.exceptions import ServiceError

__all__ = ['register_exception_handlers']

logger = logging.getLogger(__name__)


def service_error_response(request: Request, exc: ServiceError) -> JSONResponse:
    """Log a ServiceError and build its response. Shared with UnhandledErrorMiddleware."""
    status = exc.status_code
    method = request.method
    path = request.url.path

    if status >= HTTPStatus.INTERNAL_SERVER_ERROR:
        logger.error('%s %s -> %d: %s', method, path, status, type(exc).__name__, exc_info=exc)
        detail = status.phrase
    else:
        detail = exc.detail or status.phrase
        logger.warning('%s %s -> %d: %s: %s', method, path, status, type(exc).__name__, detail)

    return JSONResponse({'detail': detail}, status_code=status, headers=exc.headers)


async def _service_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ServiceError):  # pragma: no cover
        raise exc

    return service_error_response(request, exc)


async def _app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error('%s %s -> 500: %s', request.method, request.url.path, type(exc).__name__, exc_info=exc)

    return JSONResponse({'detail': 'Internal Server Error'}, status_code=500)


def register_exception_handlers(app: FastAPI) -> None:
    """Register handlers for ServiceError and AppError unless the app already has its own."""
    if ServiceError not in app.exception_handlers:
        app.add_exception_handler(ServiceError, _service_error_handler)

    if AppError not in app.exception_handlers:
        app.add_exception_handler(AppError, _app_error_handler)
