"""
Type-checked only (ty and pyright run over tests/): the types a consumer sees from the public API.

Never executed: pytest does not collect it, and nothing imports it.
"""

from http import HTTPStatus
from typing import assert_type

from python3_commons.auth import TokenData

from fastapi_commons import (
    NotFoundError,
    ServiceError,
    get_correlation_id,
    get_token_verifier,
)


class Claims(TokenData):
    tenant: str | None = None


verify = get_token_verifier(TokenData)
verify_claims = get_token_verifier(Claims)
verify_optional = get_token_verifier(Claims, required=False)


async def consumer() -> None:
    assert_type(await verify(), TokenData)
    assert_type(await verify_claims(), Claims)
    assert_type(await verify_optional(), Claims | None)
    assert_type(get_correlation_id(), str | None)


class OrderNotFoundError(NotFoundError):
    pass


assert_type(OrderNotFoundError.status_code, HTTPStatus)
assert_type(OrderNotFoundError('order 1').detail, str | None)
assert_type(ServiceError(headers={'Retry-After': '5'}).headers, dict[str, str] | None)
