"""Tokens signed by local RSA keys and a JWKS of a fake provider: tests of the token verifier without network"""

import base64
import time
from http import HTTPStatus
from typing import Any

import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt
from python3_commons.auth import TokenData

from fastapi_commons.auth import get_token_verifier

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


verify_token = get_token_verifier(TokenData)


async def status_of(credentials: HTTPAuthorizationCredentials) -> int:
    try:
        await verify_token(credentials)
    except HTTPException as e:
        return e.status_code

    return HTTPStatus.OK
