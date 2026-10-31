import base64
import time
from http import HTTPStatus
from typing import Any

import aiohttp
import pytest
import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt
from python3_commons.auth import TokenData

from fastapi_commons import auth
from fastapi_commons.auth import JwksRefreshGuard, configured_audiences, get_token_verifier, key_ids

ISSUER = 'https://idp.example.com/trust'
AUDIENCE = 'api://example'

PUBLIC_KEY, PRIVATE_KEY = rsa.newkeys(1024)
NEW_PUBLIC_KEY, NEW_PRIVATE_KEY = rsa.newkeys(1024)


def b64(number: int) -> str:
    return base64.urlsafe_b64encode(number.to_bytes((number.bit_length() + 7) // 8)).rstrip(b'=').decode()


def jwk(public_key: rsa.PublicKey, kid: str) -> dict[str, str]:
    return {'kty': 'RSA', 'alg': 'RS256', 'kid': kid, 'n': b64(public_key.n), 'e': b64(public_key.e)}


OLD_JWKS = {'keys': [jwk(PUBLIC_KEY, 'old')]}
NEW_JWKS = {'keys': [jwk(PUBLIC_KEY, 'old'), jwk(NEW_PUBLIC_KEY, 'new')]}


def make_token(
    *, private_key: rsa.PrivateKey = PRIVATE_KEY, kid: str = 'old', expires_in: int = 300, **claims: object
) -> HTTPAuthorizationCredentials:
    now = int(time.time())
    payload = {'iss': ISSUER, 'sub': 'user', 'aud': AUDIENCE, 'iat': now, 'exp': now + expires_in, **claims}
    token = jwt.encode(payload, private_key.save_pkcs1().decode(), algorithm='RS256', headers={'kid': kid})

    return HTTPAuthorizationCredentials(scheme='Bearer', credentials=token)


class Provider:
    """JWKS of the provider: the cached keys until a forced refresh"""

    def __init__(self, cached: dict[str, Any], fresh: dict[str, Any]) -> None:
        self.cached = cached
        self.fresh = fresh
        self.refreshes = 0

    async def get_jwks(self, *, force_refresh: bool = False) -> dict[str, Any]:
        if force_refresh:
            self.refreshes += 1
            self.cached = self.fresh

        return self.cached


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> Provider:
    provider = Provider(OLD_JWKS, NEW_JWKS)
    monkeypatch.setattr(auth.api_auth_settings, 'enabled', True)
    monkeypatch.setattr(auth.oidc_client, 'get_jwks', provider.get_jwks)
    monkeypatch.setattr(auth, 'jwks_refresh_guard', JwksRefreshGuard(60))
    monkeypatch.setattr(auth.oidc_settings, 'audience', None)
    monkeypatch.setattr(auth.oidc_settings, 'issuer', None)
    monkeypatch.setattr(auth.oidc_settings, 'leeway', 0)

    return provider


verify_token = get_token_verifier(TokenData)


async def status_of(credentials: HTTPAuthorizationCredentials) -> int:
    try:
        await verify_token(credentials)
    except HTTPException as e:
        return e.status_code

    return HTTPStatus.OK


@pytest.mark.asyncio
@pytest.mark.usefixtures('provider')
async def test_valid_token() -> None:
    token = await verify_token(make_token())

    assert token is not None
    assert token.sub == 'user'


@pytest.mark.asyncio
@pytest.mark.usefixtures('provider')
async def test_audience_not_configured_accepts_token_with_audience() -> None:
    assert await status_of(make_token(aud='api://other')) == HTTPStatus.OK


@pytest.mark.asyncio
@pytest.mark.usefixtures('provider')
async def test_expired_and_wrong_signature() -> None:
    assert await status_of(make_token(expires_in=-10)) == HTTPStatus.UNAUTHORIZED
    assert await status_of(make_token(private_key=NEW_PRIVATE_KEY)) == HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
@pytest.mark.usefixtures('provider')
async def test_leeway(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth.oidc_settings, 'leeway', 60)

    assert await status_of(make_token(expires_in=-10)) == HTTPStatus.OK


@pytest.mark.asyncio
@pytest.mark.usefixtures('provider')
async def test_issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth.oidc_settings, 'issuer', ISSUER)

    assert await status_of(make_token()) == HTTPStatus.OK
    assert await status_of(make_token(iss='https://other.example.com')) == HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
@pytest.mark.usefixtures('provider')
async def test_any_of_audiences(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth.oidc_settings, 'audience', ('api://old', AUDIENCE))

    assert await status_of(make_token()) == HTTPStatus.OK
    assert await status_of(make_token(aud=['api://other', 'api://old'])) == HTTPStatus.OK
    assert await status_of(make_token(aud='api://other')) == HTTPStatus.UNAUTHORIZED
    assert await status_of(make_token(aud=None)) == HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
async def test_unknown_key_refreshes_jwks_once(provider: Provider) -> None:
    assert await status_of(make_token(private_key=NEW_PRIVATE_KEY, kid='new')) == HTTPStatus.OK
    assert await status_of(make_token(private_key=NEW_PRIVATE_KEY, kid='new')) == HTTPStatus.OK
    assert provider.refreshes == 1


@pytest.mark.asyncio
async def test_unknown_keys_refresh_is_limited(provider: Provider) -> None:
    assert await status_of(make_token(kid='random-1')) == HTTPStatus.OK  # the old key still verifies it
    assert await status_of(make_token(kid='random-2')) == HTTPStatus.OK

    assert provider.refreshes == 1


@pytest.mark.asyncio
@pytest.mark.usefixtures('provider')
async def test_provider_not_available(monkeypatch: pytest.MonkeyPatch) -> None:
    async def get_jwks(**_kwargs: object) -> dict[str, Any]:
        msg = 'Cannot connect'

        raise aiohttp.ClientConnectionError(msg)

    monkeypatch.setattr(auth.oidc_client, 'get_jwks', get_jwks)

    assert await status_of(make_token()) == HTTPStatus.SERVICE_UNAVAILABLE


def test_refresh_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [100.0]
    monkeypatch.setattr(auth, 'monotonic', lambda: now[0])
    guard = JwksRefreshGuard(60)

    assert guard.allow()
    assert not guard.allow()

    now[0] += 61

    assert guard.allow()


def test_helpers() -> None:
    assert key_ids(NEW_JWKS) == {'old', 'new'}
    assert key_ids({}) == set()
    assert configured_audiences(None) == ()
    assert configured_audiences(('',)) == ()
    assert configured_audiences('a') == ('a',)
    assert configured_audiences(['a', 'b']) == ('a', 'b')
