"""
OIDC bearer-token and API-key authentication for FastAPI.

Bearer tokens are verified against the provider's JWKS through one ``OIDCClient`` per application. The client is
created and closed by ``oidc_lifespan``, which the application enters from its own lifespan::

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        async with oidc_lifespan(app, OIDCSettings()):
            yield

    verify = get_token_verifier(TokenData)

The verifier reads the client from the state of the application that serves the request (``request.app.state``), so
a mounted sub-application must run its own ``oidc_lifespan`` or not use the verifier. Tests replace the verifier with
``app.dependency_overrides[verify] = ...``.
"""

import logging
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Coroutine, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Annotated, Any, Final, Literal, overload
from uuid import UUID

import aiohttp
import jwt
import msgspec
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jwt.types import Options
from python3_commons.auth import OIDCClient, OIDCError, TokenData
from python3_commons.conf import OIDCSettings
from starlette.requests import HTTPConnection, Request

# Loaded on first use only: importing the model registers the ``api_keys`` table on python3-commons' shared Base.
lazy from python3_commons.db.models.auth import ApiKey
lazy from sqlalchemy import select
lazy from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ['OIDCState', 'get_api_key_verifier', 'get_oidc', 'get_token_verifier', 'oidc_lifespan']

logger = logging.getLogger(__name__)

_STATE_ATTRIBUTE: Final = 'fastapi_commons_oidc'
# Asymmetric JWS algorithms only: a symmetric algorithm would verify with the public JWKS as the secret, and 'none'
# would verify nothing. The value is the JWK key type the algorithm needs.
_KEY_TYPES: Final[Mapping[str, str]] = {
    'RS256': 'RSA',
    'RS384': 'RSA',
    'RS512': 'RSA',
    'PS256': 'RSA',
    'PS384': 'RSA',
    'PS512': 'RSA',
    'ES256': 'EC',
    'ES256K': 'EC',
    'ES384': 'EC',
    'ES512': 'EC',
    'EdDSA': 'OKP',
}
_BEARER_CHALLENGE: Final = {'WWW-Authenticate': 'Bearer'}
_INVALID_TOKEN_CHALLENGE: Final = {'WWW-Authenticate': 'Bearer error="invalid_token"'}
_API_KEY_CHALLENGE: Final = {'WWW-Authenticate': 'APIKey'}
# Failures of the provider round trip (discovery document, JWKS), caught around the OIDCClient calls only:
# network errors, timeouts and python3-commons' JWKS backoff (OSError: ConnectionRefusedError, TimeoutError, and the
# PermissionError/InterruptedError of HTTP 401/403/429), other HTTP errors (LookupError for 404, ValueError for 400),
# a discovery document without jwks_uri (KeyError) and documents that do not parse (OIDCError, aiohttp errors).
_PROVIDER_ERRORS: Final = (OSError, aiohttp.ClientError, OIDCError, LookupError, ValueError)

_bearer = HTTPBearer(auto_error=False)

type SessionDependency = Callable[..., AsyncSession | Awaitable[AsyncSession] | AsyncIterator[AsyncSession]]


@dataclass(frozen=True, slots=True)
class OIDCState:
    """The OIDC client of an application and the settings its tokens are verified with."""

    client: OIDCClient
    settings: OIDCSettings


@asynccontextmanager
async def oidc_lifespan(app: FastAPI, settings: OIDCSettings, **client_overrides: object) -> AsyncGenerator[OIDCState]:
    """
    Create the application's OIDC client, keep it on ``app.state`` while the context is open, then close it.

    ``settings.authority_url`` is required; ``client_id`` is not, because verifying tokens does not use it.
    ``client_overrides`` go to ``OIDCClient.from_settings`` (for example ``session=`` or ``audit_name=``).
    """
    if settings.authority_url is None and client_overrides.get('authority_url') is None:
        msg = 'OIDC authority_url must be set (OIDC_AUTHORITY_URL)'

        raise ValueError(msg)

    client = OIDCClient.from_settings(settings, **{'client_id': settings.client_id or '', **client_overrides})
    state = OIDCState(client=client, settings=settings)
    setattr(app.state, _STATE_ATTRIBUTE, state)

    try:
        yield state
    finally:
        delattr(app.state, _STATE_ATTRIBUTE)
        await client.aclose()


def get_oidc(connection: HTTPConnection) -> OIDCState:
    """The OIDC state of the application serving this request. RuntimeError when ``oidc_lifespan`` is not running."""
    state = getattr(connection.app.state, _STATE_ATTRIBUTE, None)

    if not isinstance(state, OIDCState):
        msg = 'OIDC is not set up: enter fastapi_commons.auth.oidc_lifespan(app, settings) in the application lifespan'

        raise RuntimeError(msg)  # noqa: TRY004  # a missing setup, not a wrong argument type

    return state


def _invalid_token(reason: str | Exception) -> HTTPException:
    logger.info('Rejected bearer token: %s', reason)

    return HTTPException(HTTPStatus.UNAUTHORIZED, 'Token is invalid', headers=_INVALID_TOKEN_CHALLENGE)


def _usable_key(key: Mapping[str, Any], algorithm: str) -> bool:
    """A signing key of the key type the algorithm needs; a key that names another algorithm is not used."""
    return (
        key.get('kty') == _KEY_TYPES[algorithm]
        and key.get('use') in {None, 'sig'}
        and key.get('alg') in {None, algorithm}
    )


async def _candidate_keys(client: OIDCClient, kid: str | None) -> Sequence[object]:
    """The key with this kid (an unknown kid refreshes the JWKS once), or every JWKS key when there is no kid."""
    if kid is not None:
        key = await client.get_signing_key(kid)

        return [key] if key is not None else []

    jwks = await client.get_jwks()

    if not isinstance(jwks, Mapping) or not isinstance(keys := jwks.get('keys'), list):
        msg = 'The JWKS document has no list of keys'

        raise OIDCError(msg)

    return keys


def _signing_keys(candidates: Sequence[object], algorithm: str) -> list[Mapping[str, Any]]:
    return [key for key in candidates if isinstance(key, Mapping) and _usable_key(key, algorithm)]


def _decode(token: str, keys: Sequence[Mapping[str, Any]], algorithm: str, settings: OIDCSettings) -> dict[str, Any]:
    audience = list(settings.audience) if settings.audience else None
    options: Options = {'require': ['exp'], 'verify_aud': audience is not None, 'enforce_minimum_key_length': True}
    error: jwt.PyJWTError | None = None

    for key in keys:
        try:
            signing_key = jwt.PyJWK(dict(key), algorithm=algorithm)
        except jwt.PyJWTError as e:
            logger.debug('Skipping unusable JWK %s: %s', key.get('kid'), e)
            error = e

            continue

        try:
            return jwt.decode(
                token,
                signing_key,
                algorithms=[algorithm],
                options=options,
                audience=audience,
                issuer=settings.issuer or None,
                leeway=settings.leeway,
            )
        except (jwt.InvalidSignatureError, jwt.InvalidKeyError) as e:  # another key may match (no kid in the token)
            error = e

    raise error or jwt.InvalidTokenError('no usable signing key')


async def _verify_token[T: TokenData](oidc: OIDCState, token: str, token_cls: type[T], algorithms: frozenset[str]) -> T:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        raise _invalid_token(e) from e

    if not isinstance(algorithm := header.get('alg'), str) or algorithm not in algorithms:
        reason = f'algorithm {algorithm!r} is not allowed'

        raise _invalid_token(reason)

    kid = header.get('kid')

    try:
        candidates = await _candidate_keys(oidc.client, kid if isinstance(kid, str) else None)
    except _PROVIDER_ERRORS as e:
        msg = 'OIDC provider is not available'
        logger.warning('%s: %r', msg, e)

        raise HTTPException(HTTPStatus.SERVICE_UNAVAILABLE, msg) from e

    if not (keys := _signing_keys(candidates, algorithm)):
        reason = f'no signing key for kid {kid!r}'

        raise _invalid_token(reason)

    try:
        payload = _decode(token, keys, algorithm, oidc.settings)
    except jwt.ExpiredSignatureError as e:
        raise HTTPException(HTTPStatus.UNAUTHORIZED, 'Token has expired', headers=_INVALID_TOKEN_CHALLENGE) from e
    except jwt.PyJWTError as e:
        raise _invalid_token(e) from e

    try:
        return msgspec.convert(payload, type=token_cls)
    except msgspec.ValidationError as e:
        raise _invalid_token(e) from e


@overload
def get_token_verifier[T: TokenData](
    token_cls: type[T], *, required: Literal[True] = True, algorithms: Sequence[str] = ('RS256',)
) -> Callable[..., Coroutine[Any, Any, T]]: ...


@overload
def get_token_verifier[T: TokenData](
    token_cls: type[T], *, required: Literal[False], algorithms: Sequence[str] = ('RS256',)
) -> Callable[..., Coroutine[Any, Any, T | None]]: ...


def get_token_verifier[T: TokenData](
    token_cls: type[T], *, required: bool = True, algorithms: Sequence[str] = ('RS256',)
) -> Callable[..., Coroutine[Any, Any, T | None]]:
    """
    A FastAPI dependency that verifies the request's bearer token and returns its claims as ``token_cls``.

    Without bearer credentials it answers 401 when ``required``, otherwise it returns None (so another scheme, e.g. an
    API key or Basic auth, can take over); an invalid bearer token is always 401.
    The audience is checked only when ``OIDC_AUDIENCE`` is set (then ``aud`` is required and any configured value is
    accepted), the issuer only when ``OIDC_ISSUER`` is set. A provider that cannot be reached gives 503.
    ``algorithms`` accepts asymmetric JWS algorithms only.
    """
    allowed = frozenset(algorithms)

    rejected = sorted(allowed - _KEY_TYPES.keys())

    if not allowed or rejected:
        msg = f'Only asymmetric JWS algorithms are allowed, got {rejected or "none"}'

        raise ValueError(msg)

    async def verify_token(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    ) -> T | None:
        if credentials is None:
            if required:
                raise HTTPException(HTTPStatus.UNAUTHORIZED, 'Not authenticated', headers=_BEARER_CHALLENGE)

            return None

        return await _verify_token(get_oidc(request), credentials.credentials, token_cls, allowed)

    return verify_token


def get_api_key_verifier(
    session_dependency: SessionDependency, *, header_name: str = 'X-API-Key'
) -> Callable[..., Coroutine[Any, Any, ApiKey]]:
    """
    A FastAPI dependency that looks the request's API key up in python3-commons' ``api_keys`` table.

    The key is the row's UUID primary key, so it is stored in plaintext. Keys that are not UUIDs are rejected without
    a query; expired keys (``expires_at`` in the past) are rejected. ``session_dependency`` may return the session or
    yield it.
    """
    header = APIKeyHeader(name=header_name, auto_error=False)

    async def verify_api_key(
        api_key: Annotated[str | None, Depends(header)],
        session: Annotated[AsyncSession, Depends(session_dependency)],
    ) -> ApiKey:
        if not api_key:
            raise HTTPException(HTTPStatus.UNAUTHORIZED, 'Not authenticated', headers=_API_KEY_CHALLENGE)

        try:
            key_id = UUID(api_key)
        except ValueError:
            raise HTTPException(HTTPStatus.UNAUTHORIZED, 'Invalid API key', headers=_API_KEY_CHALLENGE) from None

        result = await session.execute(select(ApiKey).where(ApiKey.uid == key_id))

        if (key := result.scalar_one_or_none()) is None or _expired(key.expires_at):
            raise HTTPException(HTTPStatus.UNAUTHORIZED, 'Invalid API key', headers=_API_KEY_CHALLENGE)

        return key

    return verify_api_key


def _expired(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False

    if expires_at.tzinfo is None:  # a database without time zones: stored as UTC
        expires_at = expires_at.replace(tzinfo=UTC)

    return expires_at <= datetime.now(UTC)
