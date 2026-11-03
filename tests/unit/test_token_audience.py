from http import HTTPStatus

import pytest

from fastapi_commons import auth
from fastapi_commons.auth import configured_audiences
from tests.unit.oidc_tokens import AUDIENCE, make_token, status_of


@pytest.mark.asyncio
@pytest.mark.usefixtures('provider')
async def test_audience_not_configured_is_not_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth.oidc_settings, 'audience', None)

    assert await status_of(make_token(aud='api://other')) == HTTPStatus.OK

    monkeypatch.setattr(auth.oidc_settings, 'audience', ('',))  # OIDC_AUDIENCE=''

    assert await status_of(make_token(aud='api://other')) == HTTPStatus.OK


@pytest.mark.asyncio
@pytest.mark.usefixtures('provider')
async def test_audience_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth.oidc_settings, 'audience', AUDIENCE)

    assert await status_of(make_token()) == HTTPStatus.OK
    assert await status_of(make_token(aud='api://other')) == HTTPStatus.UNAUTHORIZED


def test_configured_audiences() -> None:
    assert configured_audiences(None) == ()
    assert configured_audiences(('',)) == ()
    assert configured_audiences('a') == ('a',)
    assert configured_audiences(['a', 'b']) == ('a', 'b')
