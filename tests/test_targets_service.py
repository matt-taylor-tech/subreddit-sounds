"""targets_service CRUD and the legacy backfill (issue #17)."""

import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Target  # noqa: E402
from app.services import targets_service  # noqa: E402

Base.metadata.create_all(bind=engine)


def _fresh_db():
    db = SessionLocal()
    db.query(Target).delete()
    db.commit()
    return db


def test_crud_roundtrip():
    db = _fresh_db()
    try:
        t = targets_service.create_target(db, name="Metal", playlist_id="P1", subreddits="Metal", cap=30)
        assert t.id is not None and t.cap == 30 and t.enabled is True

        got = targets_service.get_target(db, t.id)
        assert got.name == "Metal"

        targets_service.update_target(db, t.id, cap=10, enabled=False)
        db.refresh(t)
        assert t.cap == 10 and t.enabled is False

        assert targets_service.delete_target(db, t.id) is True
        assert targets_service.get_target(db, t.id) is None
    finally:
        db.close()


def test_list_enabled_only():
    db = _fresh_db()
    try:
        targets_service.create_target(db, name="on", playlist_id="P1", enabled=True)
        targets_service.create_target(db, name="off", playlist_id="P2", enabled=False)
        assert {t.name for t in targets_service.list_targets(db)} == {"on", "off"}
        assert [t.name for t in targets_service.list_targets(db, enabled_only=True)] == ["on"]
    finally:
        db.close()


def test_update_unknown_field_ignored_and_missing_returns_none():
    db = _fresh_db()
    try:
        t = targets_service.create_target(db, name="x", playlist_id="P", bogus="nope")
        assert not hasattr(t, "bogus")
        assert targets_service.update_target(db, 99999, cap=5) is None
    finally:
        db.close()


def test_backfill_creates_default_from_legacy(monkeypatch):
    _fresh_db().close()
    legacy = {
        "spotify_playlist_id": "PLLEGACY",
        "reddit_subreddit": "Metal, jazz",
        "spotify_genre_filter": "metal",
        "sync_cap": "40",
        "bandcamp_enabled": "true",
        "bandcamp_tags": "post-rock",
        "bandcamp_enabled_tags": "post-rock",
        "blocklist_enabled": "true",
        "blocklist_ids": "X,Y",
        "last_desired_ids": "A,B,C",
        "sync_hour": "9",
        "sync_minute": "30",
    }
    monkeypatch.setattr(targets_service.settings_service, "get", lambda k, d="": legacy.get(k, d))

    created = targets_service.backfill_default_target()
    assert created is not None

    db = SessionLocal()
    try:
        targets = targets_service.list_targets(db)
        assert len(targets) == 1
        t = targets[0]
        assert t.name == "Default"
        assert t.playlist_id == "PLLEGACY"
        assert t.subreddits == "Metal, jazz"
        assert t.genre_filter == "metal"
        assert t.cap == 40
        assert t.bandcamp_enabled is True
        assert t.blocklist_enabled is True
        assert t.blocklist_ids == "X,Y"
        # Critical: the deletion baseline is copied verbatim.
        assert t.last_desired_ids == "A,B,C"
        assert t.sync_hour == 9 and t.sync_minute == 30
    finally:
        db.close()


def test_backfill_is_idempotent(monkeypatch):
    _fresh_db().close()
    monkeypatch.setattr(
        targets_service.settings_service, "get", lambda k, d="": {"spotify_playlist_id": "PL"}.get(k, d)
    )
    assert targets_service.backfill_default_target() is not None
    # Second call is a no-op because a target already exists.
    assert targets_service.backfill_default_target() is None
    db = SessionLocal()
    try:
        assert len(targets_service.list_targets(db)) == 1
    finally:
        db.close()


def test_backfill_noop_without_legacy_playlist(monkeypatch):
    _fresh_db().close()
    monkeypatch.setattr(targets_service.settings_service, "get", lambda k, d="": d)  # nothing configured
    assert targets_service.backfill_default_target() is None
    db = SessionLocal()
    try:
        assert targets_service.list_targets(db) == []
    finally:
        db.close()
