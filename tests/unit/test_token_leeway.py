from http import HTTPStatus

import pytest

from fastapi_commons import auth
from tests.unit.oidc_tokens import make_token, status_of


@pytest.mark.asyncio
@pytest.mark.usefixtures('provider')
async def test_no_leeway_by_default() -> None:
    assert await status_of(make_token(expires_in=-10)) == HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
@pytest.mark.usefixtures('provider')
async def test_leeway(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth.oidc_settings, 'leeway', 60)

    assert await status_of(make_token(expires_in=-10)) == HTTPStatus.OK
    assert await status_of(make_token(expires_in=-120)) == HTTPStatus.UNAUTHORIZED
