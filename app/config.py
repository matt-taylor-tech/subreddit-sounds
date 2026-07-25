from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Placeholder secret keys that must never sign real session cookies.
INSECURE_SECRET_KEYS = {"", "change-me", "change-me-in-production", "changeme"}


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

    @model_validator(mode="after")
    def _reject_insecure_secret_key_in_production(self) -> "Settings":
        if self.environment.lower() == "production" and self.secret_key in INSECURE_SECRET_KEYS:
            raise ValueError(
                "SECRET_KEY is unset or still a default placeholder while "
                "ENVIRONMENT=production. Session cookies would be forgeable. "
                "Generate a strong value, e.g. "
                '`python -c "import secrets; print(secrets.token_urlsafe(48))"`, '
                "and set SECRET_KEY in your .env before starting."
            )
        return self


settings = Settings()
