import logging
from collections.abc import Callable, Coroutine, MutableMapping
from http import HTTPStatus
from typing import Annotated, Any, TypeVar

import msgspec
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt
from python3_commons.auth import TokenData, fetch_jwks, fetch_openid_config
from python3_commons.conf import oidc_settings

from fastapi_commons.conf import api_auth_settings

logger = logging.getLogger(__name__)

bearer_security = HTTPBearer(auto_error=api_auth_settings.enabled)
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
                openid_config = await fetch_openid_config()
                _jwks = await fetch_jwks(openid_config['jwks_uri'])
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
            raise HTTPException(
                HTTPStatus.UNAUTHORIZED,
                f'Could not validate credentials: {e!s}',
                headers={'WWW-Authenticate': 'Bearer'},
            ) from e

        return token_data

    return get_verified_token
