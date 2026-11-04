import subprocess
import sys
import textwrap

import pytest
from fastapi import FastAPI
from python3_commons.auth import OIDCClient
from starlette.requests import HTTPConnection

from fastapi_commons.auth import OIDCState, get_oidc, oidc_lifespan
from tests.unit.auth.tokens import AUTHORITY, settings


def connection_of(app: FastAPI) -> HTTPConnection:
    return HTTPConnection({'type': 'http', 'app': app, 'headers': []})


@pytest.mark.asyncio
async def test_state_lives_for_the_context_and_the_client_is_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[OIDCClient] = []

    async def aclose(self: OIDCClient) -> None:
        closed.append(self)

    monkeypatch.setattr(OIDCClient, 'aclose', aclose)
    app = FastAPI()
    oidc_settings = settings(jwks_cache_ttl=12.5, jwks_refresh_interval=3.0)

    async with oidc_lifespan(app, oidc_settings) as state:
        assert get_oidc(connection_of(app)) is state
        assert state.settings is oidc_settings
        assert str(state.client._authority_url) == f'{AUTHORITY}'
        assert state.client._jwks_cache_ttl == 12.5
        assert state.client._min_refresh_interval == 3.0
        assert closed == []

    assert closed == [state.client]

    with pytest.raises(RuntimeError, match='OIDC is not set up'):
        get_oidc(connection_of(app))


@pytest.mark.asyncio
async def test_client_is_closed_when_the_app_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[OIDCClient] = []

    async def aclose(self: OIDCClient) -> None:
        closed.append(self)

    monkeypatch.setattr(OIDCClient, 'aclose', aclose)
    app = FastAPI()

    with pytest.raises(LookupError):
        async with oidc_lifespan(app, settings()):
            raise LookupError

    assert len(closed) == 1
    assert getattr(app.state, 'fastapi_commons_oidc', None) is None


@pytest.mark.asyncio
async def test_client_id_is_not_required() -> None:
    app = FastAPI()

    async with oidc_lifespan(app, settings(client_id=None)) as state:
        assert isinstance(state, OIDCState)


@pytest.mark.asyncio
async def test_authority_is_required() -> None:
    with pytest.raises(ValueError, match='authority_url must be set'):
        async with oidc_lifespan(FastAPI(), settings(authority_url=None)):
            pass


@pytest.mark.asyncio
async def test_client_overrides() -> None:
    app = FastAPI()

    async with oidc_lifespan(app, settings(), audit_name='oidc', min_refresh_interval=0.0) as state:
        assert state.client._audit_name == 'oidc'
        assert state.client._min_refresh_interval == 0.0


def test_get_oidc_without_lifespan() -> None:
    with pytest.raises(RuntimeError, match='oidc_lifespan'):
        get_oidc(connection_of(FastAPI()))


def test_import_is_light() -> None:
    """Importing the module registers no table on python3-commons' Base and loads neither jose nor the models."""
    code = textwrap.dedent(
        """
        import sys
        import fastapi_commons.auth

        loaded = sorted(m for m in sys.modules if m == 'jose' or m.startswith('python3_commons.db.models'))
        print(loaded)
        """
    )
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=True)  # noqa: S603

    assert result.stdout.strip() == '[]'
