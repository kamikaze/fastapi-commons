from pydantic_settings import BaseSettings, SettingsConfigDict
from python3_commons.conf import OIDCSettings


class ApiAuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='API_AUTH_')

    enabled: bool = True


api_auth_settings = ApiAuthSettings()
oidc_settings = OIDCSettings()
