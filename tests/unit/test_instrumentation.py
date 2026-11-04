import logging
import subprocess
import sys
import textwrap
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.util._once import Once

from fastapi_commons import instrumentation


@pytest.fixture(autouse=True)
def _reset_otel(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Isolate global OpenTelemetry state of each test."""
    for name in ('OTEL_SDK_DISABLED', 'OTEL_SERVICE_NAME', 'OTEL_RESOURCE_ATTRIBUTES'):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setattr(trace, '_TRACER_PROVIDER', None)
    monkeypatch.setattr(trace, '_TRACER_PROVIDER_SET_ONCE', Once())
    monkeypatch.setattr(instrumentation, '_tracer_provider', None)
    monkeypatch.setattr(instrumentation, '_logging_instrumented', False)
    yield
    provider = instrumentation._tracer_provider
    if provider is not None:
        provider.shutdown()
    LoggingInstrumentor().uninstrument()


class FakeExporter:
    calls: list[dict[str, Any]] = []  # noqa: RUF012

    def __init__(self, **kwargs: Any) -> None:
        type(self).calls.append(kwargs)

    def export(self, spans: Any) -> Any:
        del spans
        from opentelemetry.sdk.trace.export import SpanExportResult

        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        del timeout_millis
        return True


@pytest.fixture
def fake_exporter(monkeypatch: pytest.MonkeyPatch) -> type[FakeExporter]:
    FakeExporter.calls = []
    monkeypatch.setattr(instrumentation, 'OTLPSpanExporter', FakeExporter)
    return FakeExporter


def provider_of() -> Any:
    return trace.get_tracer_provider()


def test_service_name_in_resource(fake_exporter: type[FakeExporter]) -> None:
    app = FastAPI()
    instrumentation.setup_opentelemetry(app, service_name='my-svc')

    provider = provider_of()
    assert provider.resource.attributes['service.name'] == 'my-svc'
    assert 'compose_service' not in provider.resource.attributes
    assert fake_exporter.calls == [{}]


def test_env_service_name_used(monkeypatch: pytest.MonkeyPatch, fake_exporter: type[FakeExporter]) -> None:
    del fake_exporter
    monkeypatch.setenv('OTEL_SERVICE_NAME', 'from-env')
    instrumentation.setup_opentelemetry(FastAPI())

    assert provider_of().resource.attributes['service.name'] == 'from-env'


def test_idempotent(fake_exporter: type[FakeExporter]) -> None:
    app = FastAPI()
    instrumentation.setup_opentelemetry(app, service_name='a')
    provider = provider_of()
    instrumentation.setup_opentelemetry(app, service_name='b')
    instrumentation.setup_opentelemetry(FastAPI(), service_name='c')

    assert provider_of() is provider
    assert provider.resource.attributes['service.name'] == 'a'
    assert len(fake_exporter.calls) == 1
    assert getattr(app, '_is_instrumented_by_opentelemetry', False) is True


def test_sdk_disabled_is_noop(monkeypatch: pytest.MonkeyPatch, fake_exporter: type[FakeExporter]) -> None:
    monkeypatch.setenv('OTEL_SDK_DISABLED', 'True')
    app = FastAPI()
    instrumentation.setup_opentelemetry(app, service_name='x')

    assert fake_exporter.calls == []
    assert not hasattr(app, '_is_instrumented_by_opentelemetry')
    assert not isinstance(provider_of(), instrumentation.TracerProvider)


def test_logging_untouched(fake_exporter: type[FakeExporter]) -> None:
    del fake_exporter
    root = logging.getLogger()
    handlers = list(root.handlers)
    level = root.level
    formats = [h.formatter for h in handlers]

    instrumentation.setup_opentelemetry(FastAPI(), service_name='x')

    assert root.handlers == handlers
    assert root.level == level
    assert [h.formatter for h in root.handlers] == formats
    record = logging.getLogger('probe').makeRecord('probe', logging.INFO, __file__, 1, 'm', (), None)
    assert getattr(record, 'otelTraceID', None) == '0'
    assert getattr(record, 'otelServiceName', None) == 'x'


def test_log_correlation_off(fake_exporter: type[FakeExporter]) -> None:
    del fake_exporter
    instrumentation.setup_opentelemetry(FastAPI(), service_name='x', log_correlation=False)

    assert not LoggingInstrumentor().is_instrumented_by_opentelemetry


def test_import_without_otel_raises_clear_error() -> None:
    code = textwrap.dedent(
        """
        import sys
        import fastapi  # fastapi itself uses opentelemetry.api; import it before hiding the extra's packages
        for name in ('opentelemetry.sdk', 'opentelemetry.exporter', 'opentelemetry.instrumentation'):
            sys.modules[name] = None
        try:
            import fastapi_commons.instrumentation
        except ImportError as e:
            assert "'otel' extra" in str(e), e
            assert e.__cause__ is not None
            print('ok')
        """
    )
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=False)  # noqa: S603

    assert result.stdout.strip() == 'ok', result.stderr
