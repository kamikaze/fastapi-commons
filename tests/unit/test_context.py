import subprocess
import sys

from fastapi_commons.context import correlation_id_ctx, get_correlation_id, log_context


def test_defaults_are_none() -> None:
    assert correlation_id_ctx.get() is None
    assert log_context.get() is None
    assert get_correlation_id() is None
    assert correlation_id_ctx.name == 'correlation_id'
    assert log_context.name == 'log_context'


def test_get_correlation_id_reflects_set_and_reset() -> None:
    token = correlation_id_ctx.set('abc')
    assert get_correlation_id() == 'abc'
    correlation_id_ctx.reset(token)
    assert get_correlation_id() is None


def test_import_does_not_load_web_frameworks() -> None:
    code = (
        'import sys, fastapi_commons.context; '
        "assert 'fastapi' not in sys.modules and 'starlette' not in sys.modules, sorted(sys.modules)"
    )
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=False)  # noqa: S603
    assert result.returncode == 0, result.stderr
