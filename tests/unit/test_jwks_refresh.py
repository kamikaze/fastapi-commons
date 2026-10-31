from http import HTTPStatus

import pytest

from fastapi_commons import auth
from fastapi_commons.auth import JwksRefreshGuard, key_ids
from tests.unit.oidc_tokens import NEW_JWKS, NEW_PRIVATE_KEY, Provider, make_token, status_of


@pytest.fixture(autouse=True)
def refresh_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, 'jwks_refresh_guard', JwksRefreshGuard(60))


@pytest.mark.asyncio
async def test_unknown_key_refreshes_jwks_once(provider: Provider) -> None:
    assert await status_of(make_token(private_key=NEW_PRIVATE_KEY, kid='new')) == HTTPStatus.OK
    assert await status_of(make_token(private_key=NEW_PRIVATE_KEY, kid='new')) == HTTPStatus.OK
    assert provider.refreshes == 1


@pytest.mark.asyncio
async def test_known_key_does_not_refresh(provider: Provider) -> None:
    assert await status_of(make_token()) == HTTPStatus.OK
    assert provider.refreshes == 0


@pytest.mark.asyncio
async def test_unknown_keys_refresh_is_limited(provider: Provider) -> None:
    assert await status_of(make_token(kid='random-1')) == HTTPStatus.OK  # the old key still verifies it
    assert await status_of(make_token(kid='random-2')) == HTTPStatus.OK
    assert provider.refreshes == 1


def test_refresh_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [100.0]
    monkeypatch.setattr(auth, 'monotonic', lambda: now[0])
    guard = JwksRefreshGuard(60)

    assert guard.allow()
    assert not guard.allow()

    now[0] += 61

    assert guard.allow()


def test_key_ids() -> None:
    assert key_ids(NEW_JWKS) == {'old', 'new'}
    assert key_ids({}) == set()
