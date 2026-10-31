from pydantic_settings import BaseSettings, SettingsConfigDict
from python3_commons.conf import OIDCSettings


class ApiAuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='API_AUTH_')

    enabled: bool = True


class TokenVerificationSettings(OIDCSettings):
    """OIDC settings with the ones of the token verifier"""

    issuer: str | None = None  # expected iss claim; not checked when empty


api_auth_settings = ApiAuthSettings()
oidc_settings = TokenVerificationSettings()
