from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="Listige Clone", alias="APP_NAME")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    secret_key: str = Field(default="change-me", alias="SECRET_KEY")

    admin_username: str = Field(default="admin", alias="ADMIN_USERNAME")
    admin_password: str = Field(default="change-me", alias="ADMIN_PASSWORD")

    database_url: str = Field(default="sqlite:///./data/listige.db", alias="DATABASE_URL")

    sync_enabled: bool = Field(default=True, alias="SYNC_ENABLED")
    sync_timezone: str = Field(default="America/New_York", alias="SYNC_TIMEZONE")
    sync_hour: int = Field(default=7, alias="SYNC_HOUR")
    sync_minute: int = Field(default=0, alias="SYNC_MINUTE")
    sync_cap: int = Field(default=25, alias="SYNC_CAP")

    reddit_client_id: str = Field(default="", alias="REDDIT_CLIENT_ID")
    reddit_client_secret: str = Field(default="", alias="REDDIT_CLIENT_SECRET")
    reddit_user_agent: str = Field(default="listige-clone/0.1", alias="REDDIT_USER_AGENT")
    reddit_subreddit: str = Field(default="MelodicDeathMetal", alias="REDDIT_SUBREDDIT")

    spotify_client_id: str = Field(default="", alias="SPOTIFY_CLIENT_ID")
    spotify_client_secret: str = Field(default="", alias="SPOTIFY_CLIENT_SECRET")
    spotify_redirect_uri: str = Field(default="", alias="SPOTIFY_REDIRECT_URI")
    spotify_playlist_id: str = Field(default="", alias="SPOTIFY_PLAYLIST_ID")


settings = Settings()
