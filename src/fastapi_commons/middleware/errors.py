import logging

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fastapi_commons.exceptions import ServiceError
from fastapi_commons.handlers import service_error_response

__all__ = ['UnhandledErrorMiddleware']

logger = logging.getLogger(__name__)


class UnhandledErrorMiddleware:
    """Turn unhandled exceptions into a JSON 500 response (pure ASGI).

    Without it the server's outermost handler answers with a plain-text 500 that carries no CORS or
    correlation headers. Place it inside ``CORSMiddleware`` and ``CorrelationIDMiddleware`` so the 500
    carries their headers, and place the Prometheus middleware inside it. The exception is logged once
    and not re-raised. If the response has already started it is logged and re-raised.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)

            return

        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started

            if message['type'] == 'http.response.start':
                response_started = True

            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            request = Request(scope)

            if response_started:
                logger.exception('%s %s: error after response started', request.method, request.url.path)

                raise

            if isinstance(exc, ServiceError):
                response = service_error_response(request, exc)
            else:
                logger.error('%s %s -> 500: %s', request.method, request.url.path, type(exc).__name__, exc_info=exc)  # noqa: TRY400
                response = JSONResponse({'detail': 'Internal Server Error'}, status_code=500)

            await response(scope, receive, send)
