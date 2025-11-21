import logging
from functools import wraps
from http import HTTPStatus
from inspect import signature
from typing import Never

from fastapi import HTTPException
from pydantic_core import ValidationError
from python3_commons.exceptions import AppError

logger = logging.getLogger(__name__)


def _handle_exceptions_helper(status_code, *args) -> Never:
    if args:
        raise HTTPException(status_code=status_code, detail=args[0])

    raise HTTPException(status_code=status_code)


def handle_exceptions(func):
    signature(func)

    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except AppError as e:
            msg = f'Application error: {e!s}'
            logger.exception(msg)

            return _handle_exceptions_helper(HTTPStatus.INTERNAL_SERVER_ERROR, *e.args)
        except PermissionError as e:
            logger.exception('Permission error.')
            return _handle_exceptions_helper(HTTPStatus.UNAUTHORIZED, *e.args)
        except LookupError as e:
            logger.exception('Lookup error.')
            return _handle_exceptions_helper(HTTPStatus.NOT_FOUND, *e.args)
        except ValidationError as e:
            logger.exception('Validation error.')
            return _handle_exceptions_helper(HTTPStatus.INTERNAL_SERVER_ERROR, *e.args)
        except ValueError as e:
            logger.exception('Value error.')
            return _handle_exceptions_helper(HTTPStatus.BAD_REQUEST, *e.args)
        except NotImplementedError:
            logger.exception('Not implemented.')
            return _handle_exceptions_helper(HTTPStatus.NOT_IMPLEMENTED)

    return wrapper
