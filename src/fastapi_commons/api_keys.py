"""
API keys stored in the api_keys table of python3-commons. A module of its own: importing it registers the table in the
shared metadata, the token verifier (fastapi_commons.auth) works without it
"""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader
from python3_commons.db.models.auth import ApiKey
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status


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
