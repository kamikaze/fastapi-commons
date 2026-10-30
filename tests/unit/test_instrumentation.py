import importlib
import sys
from unittest.mock import patch

import pytest

import fastapi_commons
from fastapi_commons import instrumentation


def test_package_without_opentelemetry() -> None:
    # Importing the package (e.g. for PrometheusMiddleware) does not load the OpenTelemetry SDK and exporter
    blocked = {'opentelemetry.sdk.trace': None, 'opentelemetry.exporter.otlp.proto.grpc.trace_exporter': None}
    with patch.dict(sys.modules, blocked):
        sys.modules.pop('fastapi_commons.instrumentation', None)
        importlib.reload(fastapi_commons)
        assert 'fastapi_commons.instrumentation' not in sys.modules
    importlib.reload(fastapi_commons)


def test_setup_opentelemetry_on_access() -> None:
    assert fastapi_commons.setup_opentelemetry is instrumentation.setup_opentelemetry


def test_unknown_name() -> None:
    with pytest.raises(AttributeError, match="has no attribute 'missing'"):
        _ = fastapi_commons.missing
