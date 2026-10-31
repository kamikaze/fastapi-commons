from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from python3_commons.conf import OIDCSettings


class ApiAuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='API_AUTH_')

    enabled: bool = True


class TokenVerificationSettings(OIDCSettings):
    """OIDC settings with the ones of the token verifier"""

    leeway: int = Field(default=0, ge=0)  # allowed clock skew for exp and nbf, seconds


api_auth_settings = ApiAuthSettings()
oidc_settings = TokenVerificationSettings()
