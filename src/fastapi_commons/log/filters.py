import logging

from fastapi_commons.middleware.correlation_id import correlation_id_ctx
from fastapi_commons.middleware.log_context import log_context


class LogContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if context := log_context.get():
            for key, value in context.items():
                if value:
                    setattr(record, key, value)
        else:
            log_context.set({})

        return True


class CorrelationIDFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if correlation_id := correlation_id_ctx.get():
                record.correlation_id = correlation_id
        except LookupError:
            pass

        return True
