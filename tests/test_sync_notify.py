"""run_once fires a failure notification on failure only (issue #13)."""

import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Run  # noqa: E402
from app.services import sync_service as S  # noqa: E402

Base.metadata.create_all(bind=engine)

_CFG = {
    "reddit_subreddit": "a",
    "reddit_user_agent": "UA",
    "reddit_sort": "top",
    "reddit_timeframe": "week",
    "sync_cap": "25",
    "spotify_playlist_id": "PL",
    "spotify_genre_filter": "",
    "min_track_duration_sec": "0",
    "bandcamp_enabled": "false",
    "reddit_request_delay_sec": "0",
}


def _common(monkeypatch):
    monkeypatch.setattr(S.settings_service, "get", lambda k, d="": _CFG.get(k, d))
    monkeypatch.setattr(S.reddit_service, "fetch_posts", lambda *a, **k: [])
    monkeypatch.setattr(S.reddit_service, "has_credentials", lambda: False)
    monkeypatch.setattr(S.reddit_service, "pace_next_call", lambda log=None: None)
    notified: list = []
    monkeypatch.setattr(S.notify_service, "notify_run_failed", lambda run: notified.append(run.id))
    return notified


def test_run_once_notifies_on_failure(monkeypatch):
    notified = _common(monkeypatch)
    # Spotify not connected -> run fails.
    monkeypatch.setattr(S.spotify_service, "is_connected", lambda: False)

    db = SessionLocal()
    try:
        rid = S.SyncService().run_once(db=db, trigger_type="scheduled", dry_run=False)
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
        rid = S.SyncService().run_once(db=db, trigger_type="scheduled", dry_run=False)
        assert db.get(Run, rid).status == "success"
        assert notified == []  # no notification on success
    finally:
        db.close()
