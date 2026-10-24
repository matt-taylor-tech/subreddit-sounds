"""Cached "what's in this playlist right now" for the dashboard.

Rendering the dashboard took three Spotify calls per playlist (name, track ids,
track names), one playlist after another, on every load. Snapshots are now
cached for a few minutes, fetched concurrently when stale, and dropped whenever
a sync writes to that playlist so the dashboard never shows a pre-sync list.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from app.services import spotify_service

TTL_SEC = 300
_MAX_WORKERS = 4

_lock = Lock()
_cache: dict[str, tuple[float, dict]] = {}  # playlist_id -> (fetched_at, snapshot)


def invalidate(playlist_id: str) -> None:
    with _lock:
        _cache.pop(playlist_id, None)


def clear() -> None:
    with _lock:
        _cache.clear()


def _fetch(playlist_id: str) -> dict:
    name = spotify_service.get_playlist_name(playlist_id)
    track_ids = spotify_service.get_playlist_track_ids(playlist_id)
    info = spotify_service.get_tracks_info(track_ids)
    return {"name": name, "tracks": [info.get(tid, tid) for tid in track_ids]}


def get_many(playlist_ids: list[str]) -> dict[str, dict]:
    """{playlist_id: {"name", "tracks"}} for each id that could be loaded.

    A playlist Spotify can't return (deleted, no access, network) is simply
    left out, as before; the dashboard shows it without a track list.
    """
    now = time.monotonic()
    result: dict[str, dict] = {}
    stale: list[str] = []
    with _lock:
        for pid in dict.fromkeys(playlist_ids):
            hit = _cache.get(pid)
            if hit and now - hit[0] < TTL_SEC:
                result[pid] = hit[1]
            else:
                stale.append(pid)
    if not stale:
        return result

    # Refresh the token once up front, so parallel workers don't all race to
    # refresh it at the same moment.
    spotify_service.get_access_token()
    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(stale))) as pool:
        futures = {pid: pool.submit(_fetch, pid) for pid in stale}
    for pid, future in futures.items():
        try:
            snapshot = future.result()
        except Exception:
            continue
        result[pid] = snapshot
        with _lock:
            _cache[pid] = (time.monotonic(), snapshot)
    return result
