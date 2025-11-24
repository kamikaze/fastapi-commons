from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiAuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='API_AUTH_')

    enabled: bool = True
