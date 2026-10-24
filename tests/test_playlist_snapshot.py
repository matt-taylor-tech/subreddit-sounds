"""Dashboard playlist snapshots: cached, fetched concurrently, dropped on write."""

import threading
import time

import pytest

from app.services import playlist_snapshot, spotify_service


@pytest.fixture(autouse=True)
def _fake_spotify(monkeypatch):
    playlist_snapshot.clear()
    calls: list[str] = []
    monkeypatch.setattr(spotify_service, "get_access_token", lambda: "tok")
    monkeypatch.setattr(spotify_service, "get_playlist_name", lambda pid: f"Name {pid}")

    def track_ids(pid):
        calls.append(pid)
        if pid == "broken":
            raise RuntimeError("404")
        time.sleep(0.2)
        return [f"{pid}-t1"]

    monkeypatch.setattr(spotify_service, "get_playlist_track_ids", track_ids)
    monkeypatch.setattr(spotify_service, "get_tracks_info", lambda ids: {i: f"Artist — {i}" for i in ids})
    yield calls
    playlist_snapshot.clear()


def test_fetches_concurrently_and_skips_failures(_fake_spotify):
    started = time.monotonic()
    out = playlist_snapshot.get_many(["A", "B", "C", "broken"])
    elapsed = time.monotonic() - started
    assert out["A"] == {"name": "Name A", "tracks": ["Artist — A-t1"]}
    assert set(out) == {"A", "B", "C"}  # the broken playlist is just left out
    assert elapsed < 0.5  # three 0.2s fetches overlapped rather than ran in series


def test_second_load_is_served_from_cache(_fake_spotify):
    playlist_snapshot.get_many(["A"])
    playlist_snapshot.get_many(["A"])
    assert _fake_spotify == ["A"]


def test_invalidate_forces_a_refetch(_fake_spotify):
    playlist_snapshot.get_many(["A"])
    playlist_snapshot.invalidate("A")
    playlist_snapshot.get_many(["A"])
    assert _fake_spotify == ["A", "A"]


def test_expired_entries_are_refetched(_fake_spotify, monkeypatch):
    playlist_snapshot.get_many(["A"])
    monkeypatch.setattr(playlist_snapshot, "TTL_SEC", 0)
    playlist_snapshot.get_many(["A"])
    assert _fake_spotify == ["A", "A"]


def test_token_is_refreshed_once_before_fanning_out(monkeypatch, _fake_spotify):
    refreshes = []
    lock = threading.Lock()

    def token():
        with lock:
            refreshes.append(threading.current_thread().name)
        return "tok"

    monkeypatch.setattr(spotify_service, "get_access_token", token)
    playlist_snapshot.get_many(["A", "B"])
    assert refreshes == [threading.current_thread().name]
