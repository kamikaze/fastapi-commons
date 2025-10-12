from pydantic import HttpUrl, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    db_dsn: PostgresDsn = None


class OIDCSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='OIDC_')

    enabled: bool = True
    authority_url: HttpUrl | None = None
    client_id: str | None = None


settings = Settings()
oidc_settings = OIDCSettings()
