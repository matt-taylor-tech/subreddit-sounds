"""Remember which Spotify track a post resolved to, across runs.

With a "top of the week" feed most posts are the same from one daily run to the
next, yet every run re-fetched each YouTube title and re-ran the Spotify
searches for it. A hit is reused for ``HIT_TTL``; a miss only for ``MISS_TTL``,
because a track that wasn't on Spotify yet (or an artist Spotify hadn't
classified) often turns up within days.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import ResolvedLink

# Bump whenever the matching logic changes, so an upgrade re-resolves
# everything instead of keeping a month of matches made by the old rules.
MATCHER_VERSION = 1
HIT_TTL = timedelta(days=30)
MISS_TTL = timedelta(days=2)


def fingerprint(
    genre_filter: str | None,
    include_substyles: bool,
    include_unclassified: bool,
    min_duration_ms: int | None,
) -> str:
    """The matching settings that can change which track a source resolves to."""
    genres = ",".join(sorted(g.strip().lower() for g in (genre_filter or "").split(",") if g.strip()))
    return f"v={MATCHER_VERSION}|g={genres}|s={int(include_substyles)}|u={int(include_unclassified)}|d={min_duration_ms or 0}"


class ResolutionCache:
    def __init__(self, db: Session, settings_fingerprint: str) -> None:
        self.db = db
        self.fingerprint = settings_fingerprint
        self.hits = 0

    def _key(self, source: str) -> str:
        return hashlib.sha256(f"{source}#{self.fingerprint}".encode()).hexdigest()

    def get(self, source: str) -> tuple[bool, str | None, str]:
        """(found, track_id, detail). ``found`` with ``track_id=None`` is a cached miss."""
        row = self.db.get(ResolvedLink, self._key(source))
        if row is None:
            return False, None, ""
        ttl = HIT_TTL if row.track_id else MISS_TTL
        if datetime.utcnow() - row.resolved_at > ttl:
            return False, None, ""
        self.hits += 1
        return True, row.track_id, row.detail

    def put(self, source: str, track_id: str | None, detail: str) -> None:
        key = self._key(source)
        row = self.db.get(ResolvedLink, key)
        if row is None:
            row = ResolvedLink(key=key)
            self.db.add(row)
        row.track_id = track_id
        row.detail = detail
        row.resolved_at = datetime.utcnow()
        self.db.commit()


def prune(db: Session) -> int:
    """Drop rows too old to be used again."""
    cutoff = datetime.utcnow() - max(HIT_TTL, MISS_TTL)
    deleted = db.query(ResolvedLink).filter(ResolvedLink.resolved_at < cutoff).delete()
    db.commit()
    return deleted
