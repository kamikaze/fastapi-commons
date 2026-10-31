from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from python3_commons.conf import OIDCSettings


class ApiAuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='API_AUTH_')

    enabled: bool = True


class TokenVerificationSettings(OIDCSettings):
    """OIDC settings with the ones of the token verifier"""

    jwks_refresh_interval: float = Field(default=60.0, ge=0)  # min seconds between JWKS refreshes on unknown kid


api_auth_settings = ApiAuthSettings()
oidc_settings = TokenVerificationSettings()
