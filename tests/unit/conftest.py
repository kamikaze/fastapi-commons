import pytest

from fastapi_commons import auth
from tests.unit.oidc_tokens import AUDIENCE, NEW_JWKS, OLD_JWKS, Provider


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> Provider:
    """Authentication on, JWKS of a fake provider, the audience of the test tokens"""
    provider = Provider(OLD_JWKS, NEW_JWKS)
    monkeypatch.setattr(auth.api_auth_settings, 'enabled', True)
    monkeypatch.setattr(auth.oidc_client, 'get_jwks', provider.get_jwks)
    monkeypatch.setattr(auth.oidc_settings, 'audience', AUDIENCE)

    return provider
