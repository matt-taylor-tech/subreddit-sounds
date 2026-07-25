"""Discover which Spotify genres a target's subreddits actually produce.

The genre filter used to be a free-text box, which asked the user to guess a
string out of Spotify's ~5,000 machine-generated genre names. Nothing in the UI
revealed that "melodic death metal" and "death metal" are both real, behave
differently, and may or may not describe the artists in *their* feed.

So instead of guessing: resolve the target's recent posts exactly as a sync
would, look up the genre Spotify actually assigns each matched artist, and hand
the user that list with counts. The options become data, not vocabulary.

This is read-only. It never touches the playlist.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime

from app.models import Target
from app.services import reddit_service, settings_service, spotify_service, sync_service

# Deliberately smaller than a sync's window: a scan runs while someone waits on a
# form submit, and a genre mix doesn't need 100 posts per subreddit to be clear.
_POSTS_PER_SUBREDDIT = 50


def _noop(_msg: str) -> None:
    pass


def scan_target(target: Target, log: Callable[[str], None] | None = None) -> dict:
    """Resolve the target's recent posts and tally their artists' Spotify genres.

    Returns the payload persisted on ``Target.genre_scan``::

        {"genres": [{"name": "death metal", "count": 14}, ...],
         "unclassified": 18, "resolved": 60, "posts": 97,
         "subreddits": ["doommetal"], "scanned_at": "2026-07-25T16:40:00"}

    Genres are ordered most-common first, which is the order the form shows them.
    """
    log = log or _noop
    subreddits = reddit_service.parse_subreddits(target.subreddits)
    if not subreddits:
        raise ValueError("Add at least one subreddit before scanning for genres.")
    if not spotify_service.is_connected():
        raise RuntimeError("Connect Spotify from the dashboard before scanning for genres.")

    user_agent = settings_service.get("reddit_user_agent")
    min_duration = sync_service.min_duration_ms()

    posts: list[dict] = []
    for name in subreddits:
        try:
            fetched = reddit_service.fetch_posts(
                name,
                user_agent,
                sort=settings_service.get("reddit_sort", "top"),
                timeframe=settings_service.get("reddit_timeframe", "week"),
                limit=_POSTS_PER_SUBREDDIT,
                log=log,
            )
        except Exception as exc:  # one bad subreddit shouldn't void the whole scan
            log(f"  [scan] r/{name} failed: {exc}")
            continue
        log(f"  [scan] r/{name}: {len(fetched)} post(s)")
        posts.extend(fetched)

    # Resolve with no genre filter, so the scan reports what the feed contains
    # rather than what the current filter already lets through.
    track_ids, _low_confidence = sync_service.collect_tracks(
        posts, log, genre_filter=None, min_duration_ms=min_duration
    )
    log(f"  [scan] resolved {len(track_ids)} track(s) from {len(posts)} post(s)")

    counts: dict[str, int] = {}
    unclassified = 0
    if track_ids:
        info = spotify_service.get_primary_artist_genres(track_ids)
        for tid in track_ids:
            _artist, genres = info.get(tid, ("", []))
            if not genres:
                unclassified += 1
                continue
            for genre in genres:
                counts[genre] = counts.get(genre, 0) + 1

    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    log(f"  [scan] {len(ordered)} distinct genre(s), {unclassified} unclassified artist(s)")
    return {
        "genres": [{"name": name, "count": count} for name, count in ordered],
        "unclassified": unclassified,
        "resolved": len(track_ids),
        "posts": len(posts),
        "subreddits": subreddits,
        "scanned_at": datetime.utcnow().isoformat(timespec="seconds"),
    }


def load_scan(target: Target) -> dict | None:
    """Parse a target's stored scan, or None when it has never been scanned."""
    raw = (target.genre_scan or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) and "genres" in data else None


def selected_genres(target: Target) -> list[str]:
    """The genre names currently filtering this target."""
    return [g.strip() for g in (target.genre_filter or "").split(",") if g.strip()]


def picker_rows(target: Target) -> list[dict]:
    """Rows for the genre checklist: every scanned genre, plus any stray picks.

    A genre the user picked before (or that has since dropped out of the feed)
    still needs a checked row, or saving the form would silently discard it.
    """
    scan = load_scan(target)
    chosen = selected_genres(target)
    chosen_lower = {g.lower() for g in chosen}
    rows: list[dict] = []
    seen: set[str] = set()
    for entry in (scan or {}).get("genres", []):
        name = entry.get("name", "")
        if not name:
            continue
        seen.add(name.lower())
        rows.append({"name": name, "count": entry.get("count", 0), "checked": name.lower() in chosen_lower})
    for name in chosen:
        if name.lower() not in seen:
            rows.append({"name": name, "count": None, "checked": True})
    return rows
