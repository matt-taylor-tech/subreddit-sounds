"""DB-backed settings store.

All user-configurable settings (API credentials, sync options, admin account)
are persisted in the ``app_settings`` table so they can be managed via the
setup wizard and the admin console rather than requiring manual .env edits.

Only ``SECRET_KEY`` and ``DATABASE_URL`` must be set in the environment
before the app starts.
"""

from __future__ import annotations

from app.db import SessionLocal
from app.models import AppSetting

# Sensible defaults for non-secret settings.
DEFAULTS: dict[str, str] = {
    "admin_username": "admin",
    "sync_cap": "25",
    "sync_hour": "7",
    "sync_minute": "0",
    "sync_timezone": "America/New_York",
    "reddit_user_agent": "web:listige-clone:0.1 (by /u/suiifelse)",
    "reddit_subreddit": "MelodicDeathMetal",
    "reddit_sort": "top",
    "reddit_timeframe": "week",
    "sync_enabled": "true",
    "spotify_redirect_uri": "http://127.0.0.1:8000/callback",
    "min_track_duration_sec": "120",
}

_SECRET_KEYS = {
    "admin_password_hash",
    "spotify_client_id",
    "spotify_client_secret",
    "spotify_redirect_uri",
    "spotify_playlist_id",
    "spotify_access_token",
    "spotify_refresh_token",
    "reddit_client_id",
    "reddit_client_secret",
    "reddit_access_token",
}


def get(key: str, default: str = "") -> str:
    db = SessionLocal()
    try:
        row = db.get(AppSetting, key)
        return row.value if row else DEFAULTS.get(key, default)
    finally:
        db.close()


def put(key: str, value: str) -> None:
    db = SessionLocal()
    try:
        row = db.get(AppSetting, key)
        if row:
            row.value = value
        else:
            db.add(AppSetting(key=key, value=value, is_secret=key in _SECRET_KEYS))
        db.commit()
    finally:
        db.close()


def put_many(pairs: dict[str, str]) -> None:
    db = SessionLocal()
    try:
        for key, value in pairs.items():
            row = db.get(AppSetting, key)
            if row:
                row.value = value
            else:
                db.add(AppSetting(key=key, value=value, is_secret=key in _SECRET_KEYS))
        db.commit()
    finally:
        db.close()


def is_setup_complete() -> bool:
    """Return True once the first-run wizard has been submitted."""
    return bool(get("admin_password_hash"))
