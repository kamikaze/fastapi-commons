import os
import threading

from fastapi import FastAPI

try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.logging import LoggingInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
except ImportError as e:
    msg = "fastapi_commons.instrumentation requires the 'otel' extra: pip install 'fastapi-commons[otel]'"
    raise ImportError(msg) from e

__all__ = ['setup_opentelemetry']

_lock = threading.Lock()
_tracer_provider: TracerProvider | None = None
_logging_instrumented = False


def _sdk_disabled() -> bool:
    return os.environ.get('OTEL_SDK_DISABLED', '').strip().lower() == 'true'


def _get_tracer_provider(service_name: str | None) -> TracerProvider:
    global _tracer_provider  # noqa: PLW0603

    if _tracer_provider is None and isinstance(current := trace.get_tracer_provider(), TracerProvider):
        # Someone else (e.g. opentelemetry-instrument) already installed an SDK provider: use it, don't compete.
        _tracer_provider = current

    if _tracer_provider is None:
        attributes = {'service.name': service_name} if service_name else {}
        provider = TracerProvider(resource=Resource.create(attributes))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
        _tracer_provider = provider

    return _tracer_provider


def setup_opentelemetry(
    app: FastAPI,
    *,
    service_name: str | None = None,
    log_correlation: bool = True,
) -> None:
    """Instrument ``app`` with OpenTelemetry tracing.

    The exporter endpoint and, unless ``service_name`` is given, the resource come from the standard
    ``OTEL_*`` environment variables. The global tracer provider is created once per process (an SDK provider that
    is already installed is reused), so ``service_name`` applies to the first call only. Each app is instrumented once.
    """
    global _logging_instrumented  # noqa: PLW0603

    if _sdk_disabled():
        return

    with _lock:
        provider = _get_tracer_provider(service_name)

        if log_correlation and not _logging_instrumented:
            LoggingInstrumentor().instrument(
                tracer_provider=provider,
                set_logging_format=False,
                inject_trace_context=True,
                enable_log_auto_instrumentation=False,
            )
            _logging_instrumented = True

        if not getattr(app, '_is_instrumented_by_opentelemetry', False):
            FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
