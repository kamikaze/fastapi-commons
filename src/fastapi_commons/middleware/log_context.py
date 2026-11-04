from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Receive, Scope, Send

from fastapi_commons.context import log_context
from fastapi_commons.helpers import get_client_ip

__all__ = ('LogContextMiddleware',)


class LogContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] not in ('http', 'websocket'):
            await self.app(scope, receive, send)

            return

        ip = get_client_ip(HTTPConnection(scope))
        token = log_context.set({'client_ip': ip} if ip is not None else {})

        try:
            await self.app(scope, receive, send)
        finally:
            log_context.reset(token)
