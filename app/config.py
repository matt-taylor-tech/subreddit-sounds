from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Boot-time settings that must exist before the database is available.

    Everything else (API credentials, sync options, admin account) is stored
    in the database and managed via the first-run setup wizard.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="Listige Clone", alias="APP_NAME")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    secret_key: str = Field(default="change-me", alias="SECRET_KEY")
    database_url: str = Field(default="sqlite:///./data/listige.db", alias="DATABASE_URL")


settings = Settings()
