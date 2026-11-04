"""The public API: names per module, the lazy top-level re-exports and what importing the package loads."""

import importlib
import importlib.metadata
import subprocess
import sys
import textwrap

import pytest

import fastapi_commons

PUBLIC_API = {
    'fastapi_commons.auth': ['OIDCState', 'get_api_key_verifier', 'get_oidc', 'get_token_verifier', 'oidc_lifespan'],
    'fastapi_commons.context': ['correlation_id_ctx', 'get_correlation_id', 'log_context'],
    'fastapi_commons.exceptions': [
        'BadRequestError',
        'ConflictError',
        'ForbiddenError',
        'NotFoundError',
        'ServiceError',
        'UnauthorizedError',
        'UnavailableError',
    ],
    'fastapi_commons.handlers': ['register_exception_handlers'],
    'fastapi_commons.helpers': ['get_client_ip'],
    'fastapi_commons.instrumentation': ['setup_opentelemetry'],
    'fastapi_commons.log.filters': ['CorrelationIDFilter', 'EndpointFilter', 'LogContextFilter'],
    'fastapi_commons.middleware.correlation_id': ['CorrelationIDMiddleware'],
    'fastapi_commons.middleware.errors': ['UnhandledErrorMiddleware'],
    'fastapi_commons.middleware.log_context': ['LogContextMiddleware'],
    'fastapi_commons.middleware.prometheus': ['PrometheusMiddleware', 'metrics'],
}
# Re-exported from the package except setup_opentelemetry, which needs the otel extra.
TOP_LEVEL = sorted(
    name for module, names in PUBLIC_API.items() if module != 'fastapi_commons.instrumentation' for name in names
)
# dictConfig refers to the filters by these paths.
DICT_CONFIG_PATHS = [
    'fastapi_commons.log.filters.CorrelationIDFilter',
    'fastapi_commons.log.filters.LogContextFilter',
    'fastapi_commons.log.filters.EndpointFilter',
]


@pytest.mark.parametrize(('module', 'names'), PUBLIC_API.items())
def test_module_api(module: str, names: list[str]) -> None:
    imported = importlib.import_module(module)

    assert sorted(imported.__all__) == sorted(names)

    for name in names:
        assert hasattr(imported, name), f'{module}.{name}'


def test_top_level_api() -> None:
    assert sorted(set(fastapi_commons.__all__) - {'__version__'}) == TOP_LEVEL


@pytest.mark.parametrize('name', TOP_LEVEL)
def test_top_level_names_are_the_module_objects(name: str) -> None:
    module = next(module for module, names in PUBLIC_API.items() if name in names)

    assert getattr(fastapi_commons, name) is getattr(importlib.import_module(module), name)


@pytest.mark.parametrize('path', DICT_CONFIG_PATHS)
def test_dict_config_paths(path: str) -> None:
    module, _, name = path.rpartition('.')

    assert isinstance(getattr(importlib.import_module(module), name), type)


@pytest.mark.parametrize(
    'statement',
    [
        'import fastapi_commons',
        'from fastapi_commons import get_correlation_id',
        'import fastapi_commons.context',
        'import fastapi_commons.log.filters',
        'import fastapi_commons.exceptions',
        'import fastapi_commons.handlers',
    ],
)
def test_import_is_light(statement: str) -> None:
    """Light entry points load no tracing SDK, gRPC, Prometheus client, JWT library or database models."""
    heavy = ('grpc', 'opentelemetry.sdk', 'prometheus_client', 'jwt', 'sqlalchemy', 'python3_commons.db')
    code = textwrap.dedent(
        f"""
        import sys
        {statement}

        heavy = {heavy!r}
        print(sorted(m for m in sys.modules if m.startswith(heavy)))
        """
    )
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=True)  # noqa: S603

    assert result.stdout.strip() == '[]'


def test_version() -> None:
    assert fastapi_commons.__version__ == importlib.metadata.version('fastapi-commons')
