"""Cross-run memory of post -> Spotify track matches."""

import os
import tempfile
from datetime import timedelta

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")

import pytest  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import ResolvedLink  # noqa: E402
from app.services import resolution_cache, sync_service  # noqa: E402
from app.services.resolution_cache import ResolutionCache, fingerprint  # noqa: E402
from app.timeutil import utcnow  # noqa: E402

Base.metadata.create_all(bind=engine)


@pytest.fixture
def db():
    session = SessionLocal()
    session.query(ResolvedLink).delete()
    session.commit()
    yield session
    session.close()


def _age(db, days):
    for row in db.query(ResolvedLink).all():
        row.resolved_at = utcnow() - timedelta(days=days)
    db.commit()


def test_hits_last_longer_than_misses(db):
    cache = ResolutionCache(db, "fp")
    cache.put("yt:hit", "TRACK", "Song")
    cache.put("yt:miss", None, "Other")
    _age(db, 5)
    assert cache.get("yt:hit") == (True, "TRACK", "Song")
    assert cache.get("yt:miss") == (False, None, "")  # past MISS_TTL, so search again
    _age(db, 31)
    assert cache.get("yt:hit") == (False, None, "")


def test_different_matching_settings_do_not_share_entries(db):
    strict = fingerprint("death metal", include_substyles=False, include_unclassified=False, min_duration_ms=None)
    loose = fingerprint("death metal", include_substyles=True, include_unclassified=True, min_duration_ms=None)
    ResolutionCache(db, strict).put("yt:v", "A", "x")
    assert ResolutionCache(db, loose).get("yt:v")[0] is False
    # Genre order and case don't matter.
    assert fingerprint("Doom, death", True, True, None) == fingerprint("death,doom", True, True, None)


def test_prune_drops_only_expired_rows(db):
    cache = ResolutionCache(db, "fp")
    cache.put("yt:old", "A", "x")
    _age(db, 40)
    cache.put("yt:new", "B", "y")
    assert resolution_cache.prune(db) == 1
    assert cache.get("yt:new")[1] == "B"


def test_second_run_skips_youtube_and_spotify(db, monkeypatch):
    calls = {"meta": 0, "search": 0}

    def meta(video_id):
        calls["meta"] += 1
        return "Band - Song", "Band - Topic"

    def search(query, **kw):
        calls["search"] += 1
        return "TRACK1"

    monkeypatch.setattr(sync_service, "_youtube_meta", meta)
    monkeypatch.setattr(sync_service.spotify_service, "search_track", search)
    posts = [{"data": {"url": "https://youtu.be/abc123", "title": "Band - Song"}}]
    lines: list[str] = []

    for _ in range(2):
        ids, low = sync_service.collect_tracks(posts, lines.append, cache=ResolutionCache(db, "fp"))
        assert ids == ["TRACK1"] and low == 1

    assert calls == {"meta": 1, "search": 1}
    assert lines[-1].endswith("(cached)")
