from http import HTTPStatus
from typing import Any

import aiohttp
import pytest

from fastapi_commons import auth
from tests.unit.oidc_tokens import make_token, status_of


async def unreachable(**_kwargs: object) -> dict[str, Any]:
    msg = 'Cannot connect'

    raise aiohttp.ClientConnectionError(msg)


async def refused(**_kwargs: object) -> dict[str, Any]:
    msg = 'Connection refused'

    raise ConnectionRefusedError(msg)


@pytest.mark.asyncio
@pytest.mark.usefixtures('provider')
@pytest.mark.parametrize('get_jwks', [unreachable, refused])
async def test_provider_not_available(monkeypatch: pytest.MonkeyPatch, get_jwks: object) -> None:
    monkeypatch.setattr(auth.oidc_client, 'get_jwks', get_jwks)

    assert await status_of(make_token()) == HTTPStatus.SERVICE_UNAVAILABLE


@pytest.mark.asyncio
@pytest.mark.usefixtures('provider')
async def test_invalid_token_is_still_401() -> None:
    assert await status_of(make_token(expires_in=-10)) == HTTPStatus.UNAUTHORIZED
