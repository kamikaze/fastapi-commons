from collections.abc import Mapping
from contextvars import ContextVar

__all__ = ('correlation_id_ctx', 'get_correlation_id', 'log_context')

correlation_id_ctx: ContextVar[str | None] = ContextVar('correlation_id', default=None)
log_context: ContextVar[Mapping[str, str] | None] = ContextVar('log_context', default=None)


def get_correlation_id() -> str | None:
    return correlation_id_ctx.get()
