"""Local signing keys, a fake provider JWKS and an app wired with oidc_lifespan: the verifier without network."""

import time
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import Depends, FastAPI
from jwt.algorithms import ECAlgorithm, RSAAlgorithm
from python3_commons.auth import TokenData
from python3_commons.conf import OIDCSettings

from fastapi_commons.auth import get_token_verifier, oidc_lifespan

AUTHORITY = 'https://idp.example.com/realms/test'
ISSUER = AUTHORITY
AUDIENCE = 'api://example'

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
NEW_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
EC_KEY = ec.generate_private_key(ec.SECP256R1())

type PrivateKey = rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey


def jwk(private_key: PrivateKey, kid: str | None, **extra: str) -> dict[str, Any]:
    public_key = private_key.public_key()

    if isinstance(public_key, rsa.RSAPublicKey):
        key = RSAAlgorithm.to_jwk(public_key, as_dict=True)
    else:
        key = ECAlgorithm.to_jwk(public_key, as_dict=True)

    if kid is not None:
        key['kid'] = kid

    return {**key, **extra}


OLD_JWKS = {'keys': [jwk(KEY, 'old')]}
NEW_JWKS = {'keys': [jwk(KEY, 'old'), jwk(NEW_KEY, 'new')]}


def make_token(
    *,
    key: PrivateKey | str = KEY,
    kid: str | None = 'old',
    algorithm: str = 'RS256',
    expires_in: int = 300,
    **claims: object,
) -> str:
    """A signed token; a claim passed as None is left out."""
    now = int(time.time())
    payload = {'iss': ISSUER, 'sub': 'user', 'aud': AUDIENCE, 'iat': now, 'exp': now + expires_in, **claims}
    payload = {name: value for name, value in payload.items() if value is not None}
    headers = {'kid': kid} if kid is not None else None

    return jwt.encode(payload, key, algorithm=algorithm, headers=headers)


def bearer(token: str) -> dict[str, str]:
    return {'Authorization': f'Bearer {token}'}


class Provider:
    """The provider's JWKS: the cached keys until a forced refresh, or an error for every call."""

    def __init__(self, cached: dict[str, Any], fresh: dict[str, Any] | None = None) -> None:
        self.cached = cached
        self.fresh = fresh if fresh is not None else cached
        self.refreshes = 0
        self.error: Exception | None = None

    async def get_jwks(self, *, force_refresh: bool = False) -> dict[str, Any]:
        if self.error is not None:
            raise self.error

        if force_refresh:
            self.refreshes += 1
            self.cached = self.fresh

        return self.cached


def settings(**values: Any) -> OIDCSettings:
    """Settings for the test provider; the audience defaults to the test tokens' audience."""
    return OIDCSettings.model_validate({'authority_url': AUTHORITY, 'audience': [AUDIENCE], **values})


def build_app(
    oidc_settings: OIDCSettings,
    provider: Provider,
    monkeypatch: pytest.MonkeyPatch,
    *,
    required: bool = True,
    algorithms: Sequence[str] = ('RS256',),
) -> FastAPI:
    """An app whose lifespan runs oidc_lifespan with the fake JWKS; GET /me answers with the token's subject."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        async with oidc_lifespan(app, oidc_settings) as state:
            monkeypatch.setattr(state.client, 'get_jwks', provider.get_jwks)

            yield

    app = FastAPI(lifespan=lifespan)

    if required:
        verify = get_token_verifier(TokenData, algorithms=algorithms)

        @app.get('/me')
        async def me(token: Annotated[TokenData, Depends(verify)]) -> dict[str, str | None]:
            return {'sub': token.sub}

    else:
        verify_optional = get_token_verifier(TokenData, required=False, algorithms=algorithms)

        @app.get('/me')
        async def me_optional(token: Annotated[TokenData | None, Depends(verify_optional)]) -> dict[str, str | None]:
            return {'sub': token.sub if token else None}

    return app


@asynccontextmanager
async def serve(app: FastAPI) -> AsyncGenerator[httpx.AsyncClient]:
    """Run the app's lifespan and give a client for it; app exceptions become 500 answers."""
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url='http://test') as client,
    ):
        yield client
