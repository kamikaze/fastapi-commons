import logging
from collections.abc import Callable, Coroutine, MutableMapping
from http import HTTPStatus
from typing import Annotated, Any, TypeVar

import msgspec
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt
from python3_commons.auth import OIDCClient, TokenData

from fastapi_commons.conf import api_auth_settings, oidc_settings

logger = logging.getLogger(__name__)

bearer_security = HTTPBearer(auto_error=api_auth_settings.enabled)
oidc_client = OIDCClient(
    oidc_settings.authority_url,
    oidc_settings.client_id,
    oidc_settings.client_secret,
    timeout=oidc_settings.timeout,
    verify_cert=oidc_settings.verify_cert,
    connection_limit=oidc_settings.connection_limit,
    authority_internal_host=oidc_settings.authority_internal_host,
)
T = TypeVar('T', bound=TokenData)


def get_token_verifier[T](
    token_cls: type[T],
    jwks: MutableMapping,
) -> Callable[[HTTPAuthorizationCredentials], Coroutine[Any, Any, T | None]]:
    async def get_verified_token(
        authorization: Annotated[HTTPAuthorizationCredentials, Depends(bearer_security)],
    ) -> T | None:
        if not api_auth_settings.enabled:
            return None

        token = authorization.credentials

        try:
            if not jwks:
                async with oidc_client as client:
                    _jwks = await client.get_jwks()

                jwks.clear()
                jwks.update(_jwks)

            if oidc_settings.audience:
                audience = str(aud[0] if isinstance(aud := oidc_settings.audience, (list, tuple)) else aud)
                payload = jwt.decode(token, jwks, algorithms=['RS256'], audience=audience)
            else:
                payload = jwt.decode(token, jwks, algorithms=['RS256'])

            token_data = msgspec.convert(payload, type=token_cls)

        except ExpiredSignatureError as e:
            raise HTTPException(HTTPStatus.UNAUTHORIZED, 'Token has expired') from e
        except JWTError as e:
            raise HTTPException(HTTPStatus.UNAUTHORIZED, f'Token is invalid: {e!s}') from e
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
