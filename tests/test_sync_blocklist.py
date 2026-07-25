"""Block-list behavior through run_once (issue #11).

The decisive contrast: with the feature ON a hand-removed track stays out and is
remembered; with it OFF the same track is re-added (behavior unchanged).
"""

import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.services import sync_service as S  # noqa: E402

Base.metadata.create_all(bind=engine)


def _sp(tid):
    return {"data": {"url": f"https://open.spotify.com/track/{tid}", "title": tid}}


def _store(**overrides):
    base = {
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
    base.update(overrides)
    return base


def _wire(monkeypatch, store, current_playlist):
    monkeypatch.setattr(S.settings_service, "get", lambda k, d="": store.get(k, d))
    monkeypatch.setattr(S.settings_service, "put_many", lambda pairs: store.update(pairs))
    # Feed surfaces both T1 and T2 every run.
    monkeypatch.setattr(S.reddit_service, "fetch_posts", lambda *a, **k: [_sp("T1"), _sp("T2")])
    monkeypatch.setattr(S.reddit_service, "has_credentials", lambda: False)
    monkeypatch.setattr(S.reddit_service, "pace_next_call", lambda log=None: None)
    added: list = []
    monkeypatch.setattr(S.spotify_service, "is_connected", lambda: True)
    monkeypatch.setattr(S.spotify_service, "get_playlist_track_ids", lambda pid: list(current_playlist))
    monkeypatch.setattr(S.spotify_service, "get_tracks_info", lambda ids: {i: i for i in ids})
    monkeypatch.setattr(S.spotify_service, "add_tracks", lambda pid, ids: added.extend(ids))
    monkeypatch.setattr(S.spotify_service, "remove_tracks", lambda pid, ids: None)
    return added


def _run(dry_run=False):
    db = SessionLocal()
    try:
        S.SyncService().run_once(db=db, trigger_type="manual", dry_run=dry_run)
    finally:
        db.close()


def test_blocklist_on_keeps_manual_deletion_out(monkeypatch):
    # Last run left T1 + T2; the user has since removed T1 from the playlist.
    store = _store(blocklist_enabled="true", last_desired_ids="T1,T2")
    added = _wire(monkeypatch, store, current_playlist=["T2"])

    _run()

    assert added == []  # T1 is NOT re-added despite still trending
    assert store["blocklist_ids"].split(",") == ["T1"]  # remembered
    assert store["last_desired_ids"] == "T2"  # new baseline persisted


def test_blocklist_off_readds_the_track(monkeypatch):
    store = _store(blocklist_enabled="false", last_desired_ids="T1,T2")
    added = _wire(monkeypatch, store, current_playlist=["T2"])

    _run()

    assert added == ["T1"]  # unchanged behavior: T1 comes back
    assert "blocklist_ids" not in store  # nothing persisted when off


def test_blocklist_dry_run_persists_nothing(monkeypatch):
    store = _store(blocklist_enabled="true", last_desired_ids="T1,T2")
    added = _wire(monkeypatch, store, current_playlist=["T2"])

    _run(dry_run=True)

    assert added == []  # dry run writes nothing to Spotify
    assert "blocklist_ids" not in store  # and persists no state
