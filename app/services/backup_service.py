"""Full backups: a consistent copy of the SQLite database, and restoring one.

The JSON export (``config_io``) carries settings and playlists only. A full
backup is the database itself, so it also keeps run history, the match cache
and genre scans, and it can't fall behind when a table is added.

``restore`` accepts either format, so the same upload box works for both.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base, engine, run_migrations
from app.models import AppSetting, ResolvedLink, Run, Target
from app.services import config_io, playlist_snapshot

_SQLITE_MAGIC = b"SQLite format 3\x00"
_REQUIRED_TABLES = {"app_settings", "targets"}


def _db_path() -> Path:
    prefix = "sqlite:///"
    url = settings.database_url
    if not url.startswith(prefix) or url.endswith(":memory:"):
        raise ValueError("Full backups need a file-based SQLite database.")
    return Path(url[len(prefix) :])


def make_backup() -> bytes:
    """A consistent snapshot of the live database, safe to take while running."""
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(tmp)  # VACUUM INTO refuses to overwrite an existing file
    try:
        src = sqlite3.connect(_db_path())
        try:
            src.execute("VACUUM INTO ?", (tmp,))
        finally:
            src.close()
        return Path(tmp).read_bytes()
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def summarize(db: Session) -> dict:
    """What a database holds, in the terms the restore page reports."""
    blocked = sum(len([i for i in (t.blocklist_ids or "").split(",") if i.strip()]) for t in db.query(Target).all())

    def has(key: str) -> bool:
        row = db.get(AppSetting, key)
        return bool(row and row.value)

    return {
        "settings": db.query(func.count(AppSetting.key)).scalar(),
        "playlists": db.query(func.count(Target.id)).scalar(),
        "blocked_tracks": blocked,
        "runs": db.query(func.count(Run.id)).scalar(),
        "cached_matches": db.query(func.count(ResolvedLink.key)).scalar(),
        "has_admin": has("admin_password_hash"),
        "has_spotify": has("spotify_refresh_token"),
        "has_reddit": has("reddit_client_id") and has("reddit_client_secret"),
    }


def _check_sqlite_backup(path: str) -> None:
    """Refuse anything that isn't a plain, intact subreddit-sounds database.

    Restores are allowed from the setup page, before any login exists, so the
    file is untrusted. Triggers and views are rejected outright: copied into the
    live database they would run later, inside the app.
    """
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ValueError(f"Not a readable database: {exc}") from exc
    try:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("The backup file is damaged (integrity check failed).")
        objects = conn.execute("SELECT type, name FROM sqlite_master").fetchall()
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"Not a valid backup: {exc}") from exc
    finally:
        conn.close()
    tables = {name for kind, name in objects if kind == "table"}
    if not _REQUIRED_TABLES <= tables:
        raise ValueError("That database isn't a subreddit-sounds backup (missing its tables).")
    if any(kind in ("trigger", "view") for kind, _name in objects):
        raise ValueError("The backup contains triggers or views, which a subreddit-sounds backup never has.")


def _restore_sqlite(raw: bytes) -> None:
    fd, tmp = tempfile.mkstemp(suffix=".db")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        _check_sqlite_backup(tmp)
        # Drop pooled connections first so nothing holds the old pages open.
        engine.dispose()
        src = sqlite3.connect(tmp)
        dst = sqlite3.connect(_db_path())
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    # A backup from an older version may predate some tables and columns.
    Base.metadata.create_all(bind=engine)
    run_migrations()


def restore(raw: bytes, db: Session) -> dict:
    """Restore a full ``.db`` backup or a JSON settings export; return a summary."""
    if raw.startswith(_SQLITE_MAGIC):
        db.close()
        _restore_sqlite(raw)
    else:
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("That file is neither a full backup (.db) nor a settings export (.json).") from exc
        config_io.import_config(db, data)
    playlist_snapshot.clear()
    db.expire_all()
    return summarize(db)
