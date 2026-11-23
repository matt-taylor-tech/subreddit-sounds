"""run_once fires a failure notification on failure only (issue #13)."""

import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")

import pytest  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Run, Target  # noqa: E402
from app.services import sync_service as S  # noqa: E402

Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean_targets():
    # Test modules share one SQLite engine (bound to the first DATABASE_URL), so
    # clear targets before each test to stay order-independent.
    db = SessionLocal()
    db.query(Target).delete()
    db.commit()
    db.close()


# Global (non-target) settings the pipeline still reads from settings_service.
_GLOBAL = {
    "reddit_user_agent": "UA",
    "reddit_sort": "top",
    "reddit_timeframe": "week",
    "min_track_duration_sec": "0",
}


def _target(db):
    t = Target(name="T", enabled=True, playlist_id="PL", subreddits="a", cap=25)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _common(monkeypatch):
    monkeypatch.setattr(S.settings_service, "get", lambda k, d="": _GLOBAL.get(k, d))
    monkeypatch.setattr(S.reddit_service, "fetch_posts", lambda *a, **k: [])
    monkeypatch.setattr(S.reddit_service, "has_credentials", lambda: False)
    notified: list = []
    monkeypatch.setattr(S.notify_service, "notify_run_failed", lambda run: notified.append(run.id))
    return notified


def test_run_once_notifies_on_failure(monkeypatch):
    notified = _common(monkeypatch)
    # Spotify not connected -> run fails.
    monkeypatch.setattr(S.spotify_service, "is_connected", lambda: False)

    db = SessionLocal()
    try:
        rid = S.SyncService().run_once(db=db, target=_target(db), trigger_type="scheduled", dry_run=False)
        assert db.get(Run, rid).status == "failed"
        assert notified == [rid]
    finally:
        db.close()


def test_run_once_no_notification_on_success(monkeypatch):
    notified = _common(monkeypatch)
    monkeypatch.setattr(S.spotify_service, "is_connected", lambda: True)
    monkeypatch.setattr(S.spotify_service, "get_playlist_track_ids", lambda pid: [])
    monkeypatch.setattr(S.spotify_service, "get_tracks_info", lambda ids: {})
    monkeypatch.setattr(S.spotify_service, "add_tracks", lambda pid, ids: None)
    monkeypatch.setattr(S.spotify_service, "remove_tracks", lambda pid, ids: None)

    db = SessionLocal()
    try:
        rid = S.SyncService().run_once(db=db, target=_target(db), trigger_type="scheduled", dry_run=False)
        assert db.get(Run, rid).status == "success"
        assert notified == []  # no notification on success
    finally:
        db.close()


def _spotify_ok(monkeypatch, added: list):
    monkeypatch.setattr(S.spotify_service, "is_connected", lambda: True)
    monkeypatch.setattr(S.spotify_service, "get_playlist_track_ids", lambda pid: [])
    monkeypatch.setattr(S.spotify_service, "get_tracks_info", lambda ids: {})
    monkeypatch.setattr(S.spotify_service, "add_tracks", lambda pid, ids: added.extend(ids))
    monkeypatch.setattr(S.spotify_service, "remove_tracks", lambda pid, ids: None)


def _dead_reddit(*a, **k):
    raise RuntimeError(S.reddit_service.RSS_SHUTDOWN_MESSAGE)


def test_dead_reddit_feed_fails_the_run_and_notifies(monkeypatch):
    # Production ran "success, +0 -0" for a week after Reddit's RSS shutdown.
    notified = _common(monkeypatch)
    monkeypatch.setattr(S.reddit_service, "fetch_posts", _dead_reddit)
    _spotify_ok(monkeypatch, [])

    db = SessionLocal()
    try:
        rid = S.SyncService().run_once(db=db, target=_target(db), trigger_type="scheduled", dry_run=False)
        run = db.get(Run, rid)
        assert run.status == "failed"
        assert "RSS" in run.message
        assert notified == [rid]
    finally:
        db.close()


def test_bandcamp_still_syncs_when_reddit_is_down_but_the_run_is_flagged(monkeypatch):
    notified = _common(monkeypatch)
    monkeypatch.setattr(S.reddit_service, "fetch_posts", _dead_reddit)
    added: list = []
    _spotify_ok(monkeypatch, added)
    monkeypatch.setattr(S.bandcamp_service, "fetch_new_tracks", lambda tag: [{"artist": "A", "title": "Song"}])
    monkeypatch.setattr(S.spotify_service, "search_track", lambda *a, **k: "BC1")

    db = SessionLocal()
    try:
        t = _target(db)
        t.bandcamp_enabled = True
        t.bandcamp_tags = t.bandcamp_enabled_tags = "melodic-death-metal"
        db.commit()
        rid = S.SyncService().run_once(db=db, target=t, trigger_type="scheduled", dry_run=False)
        run = db.get(Run, rid)
        assert added == ["BC1"]  # Bandcamp still fed the playlist
        assert run.status == "failed" and run.message.startswith("Reddit:")
        assert notified == [rid]
    finally:
        db.close()
