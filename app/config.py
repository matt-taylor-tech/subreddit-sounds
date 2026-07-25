import secrets
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Known placeholder secret keys that must never sign real session cookies.
INSECURE_SECRET_KEYS = {"change-me", "change-me-in-production", "changeme"}


def _data_dir_from_db_url(db_url: str) -> Path:
    """Best-effort directory of the SQLite database, for co-locating the key."""
    prefix = "sqlite:///"
    if db_url.startswith(prefix):
        db_path = db_url[len(prefix):]
        if db_path and db_path != ":memory:":
            return Path(db_path).parent
    return Path("./data")


def _load_or_create_secret_key(key_file: Path) -> str:
    """Return a persisted secret key, generating and saving one on first run.

    The key lives in the data volume so it stays stable across restarts (a
    changing key would invalidate every existing session cookie).
    """
    try:
        existing = key_file.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except FileNotFoundError:
        pass
    key = secrets.token_urlsafe(48)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(key, encoding="utf-8")
    try:
        key_file.chmod(0o600)  # best-effort; ignored where unsupported
    except OSError:
        pass
    return key


class Settings(BaseSettings):
    """Boot-time settings that must exist before the database is available.

    Everything else (API credentials, sync options, admin account) is stored
    in the database and managed via the first-run setup wizard. With no `.env`
    at all, the app boots on sane defaults and auto-generates a secret key.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="Listige Clone", alias="APP_NAME")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    secret_key: str = Field(default="", alias="SECRET_KEY")
    database_url: str = Field(default="sqlite:///./data/listige.db", alias="DATABASE_URL")

    @model_validator(mode="after")
    def _resolve_secret_key(self) -> "Settings":
        is_placeholder = self.secret_key in INSECURE_SECRET_KEYS
        if self.secret_key and not is_placeholder:
            # A real, explicitly-provided key — honour it as-is.
            return self
        if is_placeholder and self.environment.lower() == "production":
            # Loud failure: a known-weak key would make admin sessions forgeable.
            raise ValueError(
                "SECRET_KEY is set to a known placeholder while "
                "ENVIRONMENT=production. Session cookies would be forgeable. "
                "Unset SECRET_KEY to auto-generate a strong one, or set a real value."
            )
        # Unset (or a placeholder outside production) — reuse a persisted key,
        # or generate and persist one.
        key_file = _data_dir_from_db_url(self.database_url) / "secret_key"
        self.secret_key = _load_or_create_secret_key(key_file)
        return self


settings = Settings()
