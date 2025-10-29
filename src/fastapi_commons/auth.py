import logging
from collections.abc import Callable, Coroutine, MutableMapping
from http import HTTPStatus
from typing import Annotated, Any, TypeVar

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from python3_commons.auth import TokenData, fetch_jwks, fetch_openid_config
from python3_commons.conf import oidc_settings

logger = logging.getLogger(__name__)

bearer_security = HTTPBearer(auto_error=oidc_settings.enabled)
T = TypeVar('T', bound=TokenData)


def get_token_verifier[T](
    token_cls: type[T],
    jwks: MutableMapping,
) -> Callable[[HTTPAuthorizationCredentials], Coroutine[Any, Any, T | None]]:
    async def get_verified_token(
        authorization: Annotated[HTTPAuthorizationCredentials, Depends(bearer_security)],
    ) -> T | None:
        """
        Verify the JWT access token using OIDC authority JWKS.
        """
        if not oidc_settings.enabled:
            return None

        token = authorization.credentials

        try:
            if not jwks:
                openid_config = await fetch_openid_config()
                _jwks = await fetch_jwks(openid_config['jwks_uri'])
                jwks.clear()
                jwks.update(_jwks)

            if oidc_settings.client_id:
                payload = jwt.decode(token, jwks, algorithms=['RS256'], audience=oidc_settings.client_id)
            else:
                payload = jwt.decode(token, jwks, algorithms=['RS256'])

            token_data = token_cls(**payload)
        except jwt.ExpiredSignatureError as e:
            raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail='Token has expired') from e
        except JWTError as e:
            raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=f'Token is invalid: {e!s}') from e

        return token_data

    return get_verified_token
