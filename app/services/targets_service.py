"""CRUD for playlist sync targets, plus one-time backfill from legacy config.

A ``Target`` is one Spotify playlist kept in sync with its own sources and
per-playlist settings (see ``app.models.Target``). Query helpers take a caller
``db`` session so the returned objects stay attached to that session (the sync
pipeline persists block-list state back onto the target on the same session).
``backfill_default_target`` opens its own session since it runs at startup.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Target
from app.services import settings_service

# Fields a caller may set on a target (guards create/update against stray keys).
_FIELDS = {
    "name",
    "enabled",
    "playlist_id",
    "subreddits",
    "genre_filter",
    "cap",
    "bandcamp_enabled",
    "bandcamp_tags",
    "bandcamp_enabled_tags",
    "blocklist_enabled",
    "blocklist_ids",
    "last_desired_ids",
    "sync_hour",
    "sync_minute",
}


def list_targets(db: Session, enabled_only: bool = False) -> list[Target]:
    q = db.query(Target)
    if enabled_only:
        q = q.filter(Target.enabled.is_(True))
    return q.order_by(Target.id).all()


def get_target(db: Session, target_id: int) -> Target | None:
    return db.get(Target, target_id)


def create_target(db: Session, **fields) -> Target:
    target = Target(**{k: v for k, v in fields.items() if k in _FIELDS})
    db.add(target)
    db.commit()
    db.refresh(target)
    return target


def update_target(db: Session, target_id: int, **fields) -> Target | None:
    target = db.get(Target, target_id)
    if target is None:
        return None
    for key, value in fields.items():
        if key in _FIELDS:
            setattr(target, key, value)
    db.commit()
    db.refresh(target)
    return target


def delete_target(db: Session, target_id: int) -> bool:
    target = db.get(Target, target_id)
    if target is None:
        return False
    db.delete(target)
    db.commit()
    return True


def backfill_default_target() -> Target | None:
    """Create a single "Default" target from legacy global settings, once.

    Idempotent and safe to call on every boot: no-op if any target already
    exists, or if no legacy ``spotify_playlist_id`` is configured (a fresh
    install has nothing to migrate). ``last_desired_ids`` is copied verbatim so
    the block-list's deletion baseline survives the upgrade — without it the
    first post-upgrade run would treat every current track as a manual deletion.
    """
    db = SessionLocal()
    try:
        if db.query(Target).first() is not None:
            return None
        legacy_playlist = settings_service.get("spotify_playlist_id", "")
        if not legacy_playlist:
            return None

        get = settings_service.get
        bandcamp_tags = get("bandcamp_tags", get("bandcamp_tag", ""))
        target = Target(
            name="Default",
            enabled=True,
            playlist_id=legacy_playlist,
            subreddits=get("reddit_subreddit", ""),
            genre_filter=get("spotify_genre_filter", "") or None,
            cap=int(get("sync_cap", "25")),
            bandcamp_enabled=get("bandcamp_enabled", "false") == "true",
            bandcamp_tags=bandcamp_tags,
            bandcamp_enabled_tags=get("bandcamp_enabled_tags", bandcamp_tags),
            blocklist_enabled=get("blocklist_enabled", "false") == "true",
            blocklist_ids=get("blocklist_ids", ""),
            last_desired_ids=get("last_desired_ids", ""),
            sync_hour=int(get("sync_hour", "7")),
            sync_minute=int(get("sync_minute", "0")),
        )
        db.add(target)
        db.commit()
        db.refresh(target)
        return target
    finally:
        db.close()
