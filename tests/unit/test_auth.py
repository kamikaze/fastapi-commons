from http import HTTPStatus
from typing import Annotated
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from python3_commons.db.models.auth import ApiKey
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_commons.auth import get_api_key_verifier


@pytest.mark.asyncio
async def test_create_api_key_verifier_success() -> None:
    # Mock database session
    mock_session = AsyncMock(spec=AsyncSession)
    mock_api_key = MagicMock(spec=ApiKey)
    mock_api_key.uid = 'test-key'

    # Mock result
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_api_key
    mock_session.execute.return_value = mock_result

    # Create verifier
    # We pass a mock dependency. For direct calling, we just need Any.
    verifier = get_api_key_verifier(lambda: mock_session)

    # Test the verifier directly
    result = await verifier(api_key='test-key', session=mock_session)
    assert result == mock_api_key

    # Verify DB call
    mock_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_create_api_key_verifier_fail() -> None:
    # Mock database session
    mock_session = AsyncMock(spec=AsyncSession)

    # Mock result to return None
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    # Create verifier
    verifier = get_api_key_verifier(lambda: mock_session)

    # Test the verifier directly and expect HTTPException
    with pytest.raises(HTTPException) as excinfo:
        await verifier(api_key='invalid-key', session=mock_session)

    assert excinfo.value.status_code == HTTPStatus.UNAUTHORIZED
    assert excinfo.value.detail == 'Invalid API Key'
