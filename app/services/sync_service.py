from collections.abc import Callable
from datetime import datetime
from threading import Lock

import httpx
from sqlalchemy.orm import Session

from app.models import Run, Target
from app.services import (
    bandcamp_service,
    notify_service,
    reddit_service,
    settings_service,
    spotify_service,
    targets_service,
)
from app.services.link_resolver import (
    classify_url,
    derive_artist_from_channel,
    extract_spotify_track_id,
    extract_youtube_video_id,
    is_full_album,
    is_topic_channel,
    parse_reddit_title,
    parse_youtube_title,
)
from app.services.reconcile import apply_blocklist, reconcile_latest_cap


def _parse_ids(raw: str) -> list[str]:
    """Split a comma-separated track-id string into a clean list (order preserved)."""
    return [t.strip() for t in raw.split(",") if t.strip()]


def _youtube_meta(video_id: str) -> tuple[str | None, str | None]:
    """Fetch (title, channel name) via YouTube's free oEmbed endpoint.

    Channel name is required to resolve titles that omit the artist — without it
    a freetext Spotify search for a bare song title can match any track with
    that name, even from a completely unrelated genre.
    """
    url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(url)
            if r.status_code == 200:
                data = r.json()
                return data.get("title"), data.get("author_name")
    except Exception:
        pass
    return None, None


def min_duration_ms() -> int | None:
    """Global minimum track length in ms, or None when the filter is off."""
    min_dur_sec = int(settings_service.get("min_track_duration_sec", "120"))
    return min_dur_sec * 1000 if min_dur_sec > 0 else None


def collect_tracks(
    posts: list[dict],
    log: Callable[[str], None],
    genre_filter: str | None = None,
    min_duration_ms: int | None = None,
    include_substyles: bool = True,
    include_unclassified: bool = True,
) -> tuple[list[str], int]:
    """
    Resolve each post URL to a Spotify track ID.

    Returns (track_ids_in_order, low_confidence_count).
    Direct Spotify links are high-confidence; YouTube-resolved tracks are low-confidence.
    """
    seen: set[str] = set()
    track_ids: list[str] = []
    low_confidence = 0

    for post in posts:
        data = post["data"]
        url = data.get("url", "")
        title = data.get("title", "(no title)")
        kind = classify_url(url)

        if kind == "spotify":
            track_id = extract_spotify_track_id(url)
            if track_id and track_id not in seen:
                seen.add(track_id)
                track_ids.append(track_id)
                log(f"  [spotify] {track_id}  —  {title[:70]}")

        elif kind == "youtube":
            video_id = extract_youtube_video_id(url)
            if not video_id:
                continue
            yt_title, yt_channel = _youtube_meta(video_id)
            if not yt_title:
                log(f"  [youtube] skipped (could not fetch title)  —  {title[:70]}")
                continue
            if is_full_album(yt_title):
                log(f"  [youtube] skipped (full album)  —  {yt_title[:70]}")
                continue
            artist, query = parse_youtube_title(yt_title)
            # An artist read off the video title, the Reddit post title, or a
            # "{Artist} - Topic" channel is trustworthy. A bare channel name is a
            # guess (it may be a label or curator), so it only nudges ranking
            # instead of gating the match.
            artist_is_hint = False
            source = "artist from video title"
            if not artist:
                # Music subreddits enforce "Artist - Song [Genre]", so the post
                # title names the artist far more reliably than a channel does.
                artist, reddit_query = parse_reddit_title(title)
                if artist:
                    query = reddit_query
                    source = "artist from post title"
            if not artist:
                artist = derive_artist_from_channel(yt_channel)
                artist_is_hint = not is_topic_channel(yt_channel)
                source = "guess from channel" if artist_is_hint else "artist from channel"
            track_id = spotify_service.search_track(
                query,
                artist=artist,
                genre_filter=genre_filter,
                min_duration_ms=min_duration_ms,
                artist_is_hint=artist_is_hint,
                include_substyles=include_substyles,
                include_unclassified=include_unclassified,
            )
            if track_id and track_id not in seen:
                seen.add(track_id)
                track_ids.append(track_id)
                low_confidence += 1
                log(f"  [youtube→spotify] {track_id}  —  {yt_title[:70]}  ({source}: {artist or 'none'})")
            elif not track_id:
                log(f"  [youtube] no Spotify match for: {yt_title[:70]}  ({source}: {artist or 'none'})")

        else:
            # Bandcamp / SoundCloud / article links aren't resolved yet. Logged so
            # the run history shows what a subreddit is contributing but losing.
            log(f"  [skipped] unsupported link: {url[:70]}")

    return track_ids, low_confidence


def _collect_bandcamp_tracks(
    tag: str,
    log: Callable[[str], None],
    seen: set[str],
    genre_filter: str | None = None,
    min_duration_ms: int | None = None,
    include_substyles: bool = True,
    include_unclassified: bool = True,
) -> tuple[list[str], int]:
    """Resolve Bandcamp new releases for a tag to Spotify track IDs."""
    tracks = bandcamp_service.fetch_new_tracks(tag)
    log(f"  [bandcamp] fetched {len(tracks)} track(s) from tag '{tag}'")
    track_ids: list[str] = []
    for item in tracks:
        artist, title = item["artist"], item["title"]
        track_id = spotify_service.search_track(
            title,
            artist=artist,
            genre_filter=genre_filter,
            min_duration_ms=min_duration_ms,
            include_substyles=include_substyles,
            include_unclassified=include_unclassified,
        )
        if track_id and track_id not in seen:
            seen.add(track_id)
            track_ids.append(track_id)
            log(f"  [bandcamp→spotify] {track_id}  —  {artist} - {title[:60]}")
        elif not track_id:
            log(f"  [bandcamp] no Spotify match: {artist} - {title[:60]}")
    return track_ids, len(track_ids)


def _fetch_all_posts(
    subreddits: list[str],
    user_agent: str,
    sort: str,
    timeframe: str,
    log: Callable[[str], None],
) -> list[dict]:
    """Fetch each subreddit in turn, concatenating posts.

    One failing subreddit is logged and skipped rather than aborting the whole
    run (mirrors the Bandcamp per-tag handling). Reddit requests are paced
    process-wide inside reddit_service, so no explicit spacing is needed here.
    Track-level dedup happens later in ``collect_tracks``, so overlapping posts
    across subreddits are fine.
    """
    all_posts: list[dict] = []
    for sub in subreddits:
        try:
            posts = reddit_service.fetch_posts(sub, user_agent, sort, timeframe, log=log)
            log(f"  r/{sub}: fetched {len(posts)} post(s)")
            all_posts.extend(posts)
        except Exception as exc:
            log(f"  [r/{sub}] ERROR: {exc} — skipping this subreddit")
    return all_posts


class SyncService:
    def __init__(self) -> None:
        # One lock per target id: distinct playlists can sync concurrently, but a
        # given target never double-writes (cron + manual, or two overlapping crons).
        self._locks: dict[int, Lock] = {}
        self._locks_guard = Lock()

    def _lock_for(self, target_id: int) -> Lock:
        with self._locks_guard:
            lock = self._locks.get(target_id)
            if lock is None:
                lock = Lock()
                self._locks[target_id] = lock
            return lock

    def run_all(self, db: Session, trigger_type: str, dry_run: bool = False) -> list[int]:
        """Sync every enabled target in turn; returns the created run ids."""
        run_ids: list[int] = []
        for target in targets_service.list_targets(db, enabled_only=True):
            run_id = self.run_once(db, target, trigger_type, dry_run=dry_run)
            if run_id is not None:
                run_ids.append(run_id)
        return run_ids

    def run_once(self, db: Session, target: Target, trigger_type: str, dry_run: bool = False) -> int | None:
        lock = self._lock_for(target.id or 0)
        if not lock.acquire(blocking=False):
            return None

        run = Run(
            trigger_type=trigger_type,
            dry_run=dry_run,
            status="running",
            target_id=target.id,
            target_label=target.name,
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        lines: list[str] = []

        def log(msg: str) -> None:
            lines.append(msg)

        try:
            subreddits = reddit_service.parse_subreddits(target.subreddits)
            user_agent = settings_service.get("reddit_user_agent", "web:subreddit-sounds:0.1 (by /u/suiifelse)")
            sort = settings_service.get("reddit_sort", "top")
            timeframe = settings_service.get("reddit_timeframe", "week")
            sync_cap = target.cap
            playlist_id = target.playlist_id
            genre_filter = target.genre_filter or None
            include_substyles = target.genre_include_substyles
            include_unclassified = target.genre_include_unclassified
            min_duration = min_duration_ms()

            # --- Reddit ---
            label = f"{sort}/{timeframe}" if sort == "top" else sort
            auth_label = "OAuth API" if reddit_service.has_credentials() else "public RSS"
            log(f"[{target.name}] playlist {playlist_id}")
            log(f"Fetching {len(subreddits)} subreddit(s) [{label}] via {auth_label}: {', '.join(subreddits)}")
            posts = _fetch_all_posts(subreddits, user_agent, sort, timeframe, log)
            log(f"Fetched {len(posts)} posts total — resolving links...")

            if not spotify_service.is_connected():
                log("Spotify not connected — visit the dashboard to authorise")
                run.status = "failed"
                run.message = "Spotify not connected"
                run.log = "\n".join(lines)
                run.ended_at = datetime.utcnow()
                db.add(run)
                db.commit()
                return run.id

            new_track_ids, low_conf = collect_tracks(
                posts,
                log,
                genre_filter=genre_filter,
                min_duration_ms=min_duration,
                include_substyles=include_substyles,
                include_unclassified=include_unclassified,
            )
            log(f"Resolved {len(new_track_ids)} unique track(s) from Reddit ({low_conf} via YouTube title search)")

            # --- Bandcamp ---
            bandcamp_enabled = target.bandcamp_enabled
            if bandcamp_enabled:
                enabled_tags_raw = target.bandcamp_enabled_tags or target.bandcamp_tags
                enabled_tags = [t.strip() for t in enabled_tags_raw.split(",") if t.strip()]
                bandcamp_seen = set(new_track_ids)
                for tag in enabled_tags:
                    log(f"Fetching Bandcamp new releases for tag '{tag}'...")
                    try:
                        bc_ids, bc_count = _collect_bandcamp_tracks(
                            tag,
                            log,
                            seen=bandcamp_seen,
                            genre_filter=genre_filter,
                            min_duration_ms=min_duration,
                            include_substyles=include_substyles,
                            include_unclassified=include_unclassified,
                        )
                        new_track_ids = new_track_ids + bc_ids
                        log(f"Added {bc_count} track(s) from Bandcamp tag '{tag}'")
                    except Exception as exc:
                        log(f"  [bandcamp:{tag}] ERROR: {exc}")

            # --- Resolved tracks summary ---
            track_info = spotify_service.get_tracks_info(new_track_ids)
            log(f"Resolved tracks ({len(new_track_ids)}):")
            for i, tid in enumerate(new_track_ids, 1):
                log(f"  {i:>3}. {track_info.get(tid, tid)}")

            # --- Spotify read ---
            log(f"Reading current playlist ({playlist_id})")
            current_ids = spotify_service.get_playlist_track_ids(playlist_id)
            log(f"Playlist currently has {len(current_ids)} track(s)")

            # --- Block-list (optional): make manual deletions stick ---
            blocklist_enabled = target.blocklist_enabled
            blocked: set[str] = set()
            if blocklist_enabled:
                blocked = set(_parse_ids(target.blocklist_ids))
                last_desired = _parse_ids(target.last_desired_ids)
                new_track_ids, blocked, newly_blocked = apply_blocklist(
                    new_track_ids, current_ids, last_desired, blocked
                )
                if newly_blocked:
                    log(
                        f"Block-list: {len(newly_blocked)} track(s) you removed by hand will not be "
                        f"re-added: {', '.join(track_info.get(t, t) for t in newly_blocked)}"
                    )
                log(f"Block-list active: {len(blocked)} track(s) blocked from re-adding")

            # --- Reconcile ---
            desired_ids = reconcile_latest_cap(current_ids, new_track_ids, sync_cap)
            current_set = set(current_ids)
            desired_set = set(desired_ids)

            to_add = [tid for tid in desired_ids if tid not in current_set]
            to_remove = [tid for tid in current_ids if tid not in desired_set]

            remove_info = spotify_service.get_tracks_info(to_remove)
            log(f"Tracks to add: {len(to_add)}, to remove: {len(to_remove)}")
            for tid in to_add:
                log(f"  + {track_info.get(tid, tid)}")
            for tid in to_remove:
                log(f"  - {remove_info.get(tid, tid)}")

            # --- Spotify write ---
            if dry_run:
                log("Dry run — no changes written to Spotify")
            else:
                if to_add:
                    spotify_service.add_tracks(playlist_id, to_add)
                    log(f"Added {len(to_add)} track(s)")
                if to_remove:
                    spotify_service.remove_tracks(playlist_id, to_remove)
                    log(f"Removed {len(to_remove)} track(s)")
                if not to_add and not to_remove:
                    log("Playlist already up to date — no changes needed")

            # Persist block-list state onto the target (real runs only): the
            # growing block-list, and the desired set used to detect the next
            # deletion. Per-target so playlists never clobber each other's state.
            if blocklist_enabled and not dry_run:
                target.blocklist_ids = ",".join(sorted(blocked))
                target.last_desired_ids = ",".join(desired_ids)
                db.add(target)

            run.added_count = len(to_add) if not dry_run else 0
            run.removed_count = len(to_remove) if not dry_run else 0
            run.low_confidence_count = low_conf
            run.message = (
                f"{'[dry] ' if dry_run else ''}+{len(to_add)} -{len(to_remove)} "
                f"(resolved {len(new_track_ids)} tracks, {low_conf} via YouTube)"
            )
            run.status = "success"

        except Exception as exc:
            log(f"ERROR: {type(exc).__name__}: {exc}")
            run.status = "failed"
            run.message = f"{type(exc).__name__}: {exc}"
        finally:
            run.log = "\n".join(lines)
            run.ended_at = datetime.utcnow()
            db.add(run)
            db.commit()
            failed = run.status == "failed"
            lock.release()
            # Best-effort failure notification, after releasing the lock so a slow
            # webhook can't hold up the next run. In finally (not after it) so it
            # also fires on the early-return failure paths. No-op when unconfigured.
            if failed:
                notify_service.notify_run_failed(run)

        return run.id
