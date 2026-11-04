import re
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fastapi_commons.context import correlation_id_ctx

__all__ = ('CorrelationIDMiddleware',)

_VALID_ID = re.compile(r'[A-Za-z0-9._:-]{1,64}')


class CorrelationIDMiddleware:
    def __init__(self, app: ASGIApp, *, header_name: str = 'X-Correlation-ID') -> None:
        self.app = app
        self.header_name = header_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] not in ('http', 'websocket'):
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get(self.header_name)
        correlation_id = incoming if incoming and _VALID_ID.fullmatch(incoming) else str(uuid4())

        async def send_with_header(message: Message) -> None:
            if message['type'] == 'http.response.start':
                MutableHeaders(scope=message)[self.header_name] = correlation_id
            await send(message)

        token = correlation_id_ctx.set(correlation_id)
        try:
            await self.app(scope, receive, send_with_header)
        finally:
            correlation_id_ctx.reset(token)
