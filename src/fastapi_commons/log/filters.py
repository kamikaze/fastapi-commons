import logging
import re
from collections.abc import Collection, Mapping

from fastapi_commons.context import correlation_id_ctx, log_context

__all__ = ('CorrelationIDFilter', 'EndpointFilter', 'LogContextFilter')

_REQUEST_LINE = re.compile(r'\b[A-Z]+ (\S+) HTTP/')


class CorrelationIDFilter(logging.Filter):
    def __init__(self, name: str = '', default: str = '-') -> None:
        super().__init__(name)
        self.default = default

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, 'correlation_id'):
            record.correlation_id = correlation_id_ctx.get() or self.default

        return True


class LogContextFilter(logging.Filter):
    def __init__(self, name: str = '', default: str = '-', fields: Collection[str] = ('client_ip',)) -> None:
        super().__init__(name)
        self.default = default
        self.fields = tuple(fields)

    def filter(self, record: logging.LogRecord) -> bool:
        context = log_context.get() or {}
        for key in (*self.fields, *context):
            if not hasattr(record, key):
                setattr(record, key, context.get(key) or self.default)

        return True


class EndpointFilter(logging.Filter):
    """
    Drop access-log records for exact request paths (e.g. ``/metrics``), ignoring the query string.

    Attach it to the server's access logger only (``uvicorn.access``, ``granian.access``): it reads the request path
    from the record's arguments (uvicorn's tuple, a mapping with ``path``) or from a ``METHOD /path HTTP/x`` message.
    """

    def __init__(self, name: str = '', paths: Collection[str] = ('/metrics',)) -> None:
        super().__init__(name)
        self.paths = frozenset(paths)

    @staticmethod
    def _extract_path(record: logging.LogRecord) -> str | None:
        args = record.args
        if isinstance(args, Mapping):
            if isinstance(path := args.get('path'), str):
                return path
        elif isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):  # noqa: PLR2004
            return args[2]

        try:
            message = record.getMessage()
        except TypeError, ValueError:
            return None

        return match.group(1) if (match := _REQUEST_LINE.search(message)) else None

    def filter(self, record: logging.LogRecord) -> bool:
        path = self._extract_path(record)

        return path is None or path.split('?', 1)[0] not in self.paths
