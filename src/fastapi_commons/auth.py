import logging
from collections.abc import Callable, Coroutine, Mapping, Sequence
from http import HTTPStatus
from time import monotonic
from typing import Annotated, Any

import aiohttp
import msgspec
from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWSError, JWTError, jwt
from jose.exceptions import JWTClaimsError
from python3_commons.auth import OIDCClient, TokenData
from python3_commons.db.models.auth import ApiKey
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from fastapi_commons.conf import api_auth_settings, oidc_settings

logger = logging.getLogger(__name__)

bearer_security = HTTPBearer(auto_error=api_auth_settings.enabled)
oidc_client = OIDCClient(
    oidc_settings.authority_url,
    oidc_settings.client_id,
    oidc_settings.client_secret.get_secret_value(),
    timeout=oidc_settings.timeout,
    verify_cert=oidc_settings.verify_cert,
    connection_limit=oidc_settings.connection_limit,
    authority_internal_host=oidc_settings.authority_internal_host,
)
JWT_ALGORITHMS = ['RS256']
# Errors of reaching the OIDC provider: network, timeouts, 5xx and 429 answers (ConnectionError, InterruptedError)
PROVIDER_ERRORS = (OSError, aiohttp.ClientError)


class JwksRefreshGuard:
    """Allows a JWKS refresh on an unknown kid at most once per interval: random kids do not flood the provider"""

    def __init__(self, interval: float) -> None:
        self._interval = interval
        self._refreshed_at: float | None = None

    def allow(self) -> bool:
        now = monotonic()

        if self._refreshed_at is not None and now - self._refreshed_at < self._interval:
            return False

        self._refreshed_at = now

        return True


jwks_refresh_guard = JwksRefreshGuard(oidc_settings.jwks_refresh_interval)


def key_ids(jwks: Mapping[str, Any]) -> set[str]:
    return {kid for key in jwks.get('keys', ()) if (kid := key.get('kid'))}


async def get_signing_keys(token: str) -> dict[str, Any]:
    """
    JWKS of the provider; refreshed before the cache expires when the token is signed by a key not in it (key
    rotation)
    """
    jwks = await oidc_client.get_jwks()
    kid = jwt.get_unverified_header(token).get('kid')

    if kid and kid not in key_ids(jwks) and jwks_refresh_guard.allow():
        logger.info('Token key %s is not in OIDC JWKS, refreshing it', kid)
        jwks = await oidc_client.get_jwks(force_refresh=True)

    return jwks


def configured_audiences(audience: Sequence[str] | str | None) -> tuple[str, ...]:
    """Audiences of the setting without empty values: an empty OIDC_AUDIENCE is read as ('',)"""
    audiences = (audience,) if isinstance(audience, str) else (audience or ())

    return tuple(aud for aud in audiences if aud)


def check_audience(payload: Mapping[str, Any], audiences: Sequence[str]) -> None:
    """The token is for one of the audiences (several: e.g. while clients are switched); none - not checked"""
    if not audiences:
        return

    aud = payload.get('aud')
    token_audiences = {aud} if isinstance(aud, str) else set(aud or ())

    if not token_audiences.intersection(audiences):
        msg = 'Invalid audience'

        raise JWTClaimsError(msg)


def decode_token(token: str, jwks: Mapping[str, Any]) -> dict[str, Any]:
    """Claims of a token with a valid signature, exp, nbf, iat and, when configured, iss and aud"""
    options = {'verify_at_hash': False, 'verify_aud': False, 'leeway': oidc_settings.leeway}
    payload = jwt.decode(token, jwks, algorithms=JWT_ALGORITHMS, issuer=oidc_settings.issuer or None, options=options)
    check_audience(payload, configured_audiences(oidc_settings.audience))

    return payload


def get_token_verifier[T: TokenData](
    token_cls: type[T],
) -> Callable[[HTTPAuthorizationCredentials], Coroutine[Any, Any, T | None]]:
    async def get_verified_token(
        authorization: Annotated[HTTPAuthorizationCredentials, Depends(bearer_security)],
    ) -> T | None:
        if not api_auth_settings.enabled:
            return None

        logger.debug('Getting token from request')

        token = authorization.credentials

        try:
            logger.debug('Getting OIDC JWKS')

            jwks = await get_signing_keys(token)

            logger.debug('Decoding OIDC token')

            payload = decode_token(token, jwks)

            logger.debug('Converting OIDC token to %s', token_cls.__name__)

            token_data = msgspec.convert(payload, type=token_cls)
        except ExpiredSignatureError as e:
            raise HTTPException(HTTPStatus.UNAUTHORIZED, 'Token has expired') from e
        except JWTError as e:
            raise HTTPException(HTTPStatus.UNAUTHORIZED, f'Token is invalid: {e!s}') from e
        except JWSError as e:
            raise HTTPException(HTTPStatus.UNAUTHORIZED, f'Token signature is invalid: {e!s}') from e
        except PROVIDER_ERRORS as e:
            msg = 'OIDC provider is not available'

            logger.exception(msg)

            raise HTTPException(HTTPStatus.SERVICE_UNAVAILABLE, msg) from e
        except Exception as e:
            msg = f'Could not validate credentials: {e!s}'

            logger.exception(msg)

            raise HTTPException(
                HTTPStatus.UNAUTHORIZED,
                msg,
                headers={'WWW-Authenticate': 'Bearer'},
            ) from e

        return token_data

    return get_verified_token


def get_api_key_verifier(
    db_dependency: Callable[..., AsyncSession], header_name: str = 'Api-Key'
) -> Callable[..., Coroutine[Any, Any, ApiKey]]:
    async def verify_api_key(
        api_key: Annotated[str, Depends(APIKeyHeader(name=header_name, auto_error=True))],
        session: Annotated[AsyncSession, Depends(db_dependency)],
    ) -> ApiKey:
        stmt = select(ApiKey).where(ApiKey.uid == api_key)
        result = await session.execute(stmt)
        api_key_obj = result.scalar_one_or_none()

        if not api_key_obj:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail='Invalid API Key',
                headers={'WWW-Authenticate': 'Api-Key'},
            )

        return api_key_obj

    return verify_api_key
