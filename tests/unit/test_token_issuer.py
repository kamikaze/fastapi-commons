from http import HTTPStatus

import pytest

from fastapi_commons import auth
from tests.unit.oidc_tokens import ISSUER, make_token, status_of


@pytest.mark.asyncio
@pytest.mark.usefixtures('provider')
@pytest.mark.parametrize('issuer', [None, ''])
async def test_issuer_not_configured_is_not_checked(monkeypatch: pytest.MonkeyPatch, issuer: str | None) -> None:
    monkeypatch.setattr(auth.oidc_settings, 'issuer', issuer)

    assert await status_of(make_token(iss='https://other.example.com')) == HTTPStatus.OK


@pytest.mark.asyncio
@pytest.mark.usefixtures('provider')
async def test_issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth.oidc_settings, 'issuer', ISSUER)

    assert await status_of(make_token()) == HTTPStatus.OK
    assert await status_of(make_token(iss='https://other.example.com')) == HTTPStatus.UNAUTHORIZED
