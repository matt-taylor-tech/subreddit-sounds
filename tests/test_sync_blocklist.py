"""Per-target block-list behavior through run_once (issues #11 + #17).

With the feature ON a hand-removed track stays out and is remembered on THAT
target; with it OFF the same track is re-added. Under #17 the block-list state
lives on the target row, so a deletion on one playlist must not touch another's.
"""

import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")

import pytest  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Target  # noqa: E402
from app.services import sync_service as S  # noqa: E402

Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean_targets():
    # Test modules share one SQLite engine (bound to the first DATABASE_URL), so
    # clear targets before each test to stay order-independent (run_all sees all).
    db = SessionLocal()
    db.query(Target).delete()
    db.commit()
    db.close()


_GLOBAL = {"reddit_user_agent": "UA", "reddit_sort": "top", "reddit_timeframe": "week", "min_track_duration_sec": "0"}


def _sp(tid):
    return {"data": {"url": f"https://open.spotify.com/track/{tid}", "title": tid}}


def _wire(monkeypatch, *, feed_by_sub, playlist_by_id):
    """feed_by_sub: {subreddit: [track_ids]}. playlist_by_id: {playlist_id: [track_ids]}."""
    monkeypatch.setattr(S.settings_service, "get", lambda k, d="": _GLOBAL.get(k, d))
    monkeypatch.setattr(
        S.reddit_service, "fetch_posts", lambda sub, *a, **k: [_sp(t) for t in feed_by_sub.get(sub, [])]
    )
    monkeypatch.setattr(S.reddit_service, "has_credentials", lambda: False)
    monkeypatch.setattr(S.reddit_service, "pace_next_call", lambda log=None: None)
    added: list = []
    monkeypatch.setattr(S.spotify_service, "is_connected", lambda: True)
    monkeypatch.setattr(S.spotify_service, "get_playlist_track_ids", lambda pid: list(playlist_by_id.get(pid, [])))
    monkeypatch.setattr(S.spotify_service, "get_tracks_info", lambda ids: {i: i for i in ids})
    monkeypatch.setattr(S.spotify_service, "add_tracks", lambda pid, ids: added.extend(ids))
    monkeypatch.setattr(S.spotify_service, "remove_tracks", lambda pid, ids: None)
    return added


def _make(db, **kw):
    defaults = dict(name="T", enabled=True, playlist_id="PL", subreddits="a", cap=25)
    defaults.update(kw)
    t = Target(**defaults)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def test_blocklist_on_keeps_manual_deletion_out(monkeypatch):
    # Last run left T1 + T2; the user has since removed T1 from the playlist.
    added = _wire(monkeypatch, feed_by_sub={"a": ["T1", "T2"]}, playlist_by_id={"PL": ["T2"]})
    db = SessionLocal()
    try:
        t = _make(db, blocklist_enabled=True, last_desired_ids="T1,T2")
        S.SyncService().run_once(db=db, target=t, trigger_type="manual")
        db.refresh(t)
        assert added == []  # T1 not re-added despite still trending
        assert t.blocklist_ids.split(",") == ["T1"]  # remembered on the target
        assert t.last_desired_ids == "T2"  # new baseline persisted on the target
    finally:
        db.close()


def test_blocklist_off_readds_the_track(monkeypatch):
    added = _wire(monkeypatch, feed_by_sub={"a": ["T1", "T2"]}, playlist_by_id={"PL": ["T2"]})
    db = SessionLocal()
    try:
        t = _make(db, blocklist_enabled=False, last_desired_ids="T1,T2")
        S.SyncService().run_once(db=db, target=t, trigger_type="manual")
        db.refresh(t)
        assert added == ["T1"]  # unchanged behavior: T1 comes back
        assert t.blocklist_ids == ""  # nothing persisted when off
    finally:
        db.close()


def test_blocklist_dry_run_persists_nothing(monkeypatch):
    added = _wire(monkeypatch, feed_by_sub={"a": ["T1", "T2"]}, playlist_by_id={"PL": ["T2"]})
    db = SessionLocal()
    try:
        t = _make(db, blocklist_enabled=True, last_desired_ids="T1,T2")
        S.SyncService().run_once(db=db, target=t, trigger_type="manual", dry_run=True)
        db.refresh(t)
        assert added == []  # dry run writes nothing to Spotify
        assert t.blocklist_ids == ""  # and persists no block-list state
        assert t.last_desired_ids == "T1,T2"  # baseline untouched
    finally:
        db.close()


def test_blocklist_isolation_between_targets(monkeypatch):
    # A: user removed A1 (A1 in last_desired, gone from playlist) -> A1 blocked on A.
    # B: nothing removed -> B's block-list must stay empty (no cross-contamination).
    added = _wire(
        monkeypatch,
        feed_by_sub={"suba": ["A1", "A2"], "subb": ["B1", "B2"]},
        playlist_by_id={"PLA": ["A2"], "PLB": ["B1", "B2"]},
    )
    db = SessionLocal()
    try:
        a = _make(db, name="A", playlist_id="PLA", subreddits="suba", blocklist_enabled=True, last_desired_ids="A1,A2")
        b = _make(db, name="B", playlist_id="PLB", subreddits="subb", blocklist_enabled=True, last_desired_ids="B1,B2")
        S.SyncService().run_all(db=db, trigger_type="scheduled")
        db.refresh(a)
        db.refresh(b)
        assert a.blocklist_ids.split(",") == ["A1"]  # A's deletion recorded on A
        assert b.blocklist_ids == ""  # B untouched by A's deletion
        assert added == []  # both playlists already hold their desired sets
    finally:
        db.close()
