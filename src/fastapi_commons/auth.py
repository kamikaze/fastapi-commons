import importlib
import logging
from collections.abc import Callable, Coroutine
from http import HTTPStatus
from typing import TYPE_CHECKING, Annotated, Any

import msgspec
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWSError, JWTError, jwt
from python3_commons.auth import OIDCClient, TokenData

from fastapi_commons.conf import api_auth_settings, oidc_settings

if TYPE_CHECKING:
    from fastapi_commons.api_keys import get_api_key_verifier

__all__ = ['bearer_security', 'get_api_key_verifier', 'get_token_verifier', 'oidc_client']

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
JWT_OPTIONS = {'verify_at_hash': False}


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
            async with oidc_client as client:
                logger.debug('Getting OIDC JWKS')
                jwks = await client.get_jwks()
                logger.debug('OIDC JWKS: %s', jwks)

            logger.debug('Decoding OIDC token')

            if oidc_settings.audience:
                audience = aud if isinstance(aud := oidc_settings.audience, str) else aud[0]
                payload = jwt.decode(token, jwks, algorithms=['RS256'], audience=audience, options=JWT_OPTIONS)
            else:
                payload = jwt.decode(token, jwks, algorithms=['RS256'], options=JWT_OPTIONS)

            logger.debug('Converting OIDC token to %s', token_cls.__name__)

            token_data = msgspec.convert(payload, type=token_cls)
        except ExpiredSignatureError as e:
            raise HTTPException(HTTPStatus.UNAUTHORIZED, 'Token has expired') from e
        except JWTError as e:
            raise HTTPException(HTTPStatus.UNAUTHORIZED, f'Token is invalid: {e!s}') from e
        except JWSError as e:
            raise HTTPException(HTTPStatus.UNAUTHORIZED, f'Token signature is invalid: {e!s}') from e
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


def __getattr__(name: str) -> object:
    """get_api_key_verifier moved to fastapi_commons.api_keys: imported on use, not with the token verifier"""
    if name == 'get_api_key_verifier':
        return importlib.import_module('fastapi_commons.api_keys').get_api_key_verifier

    msg = f'module {__name__!r} has no attribute {name!r}'

    raise AttributeError(msg)
