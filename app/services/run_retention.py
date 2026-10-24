"""Delete old run history so the runs table (and each run's log) can't grow forever.

Runs older than ``run_retention_days`` are removed, except each playlist's most
recent run, which the dashboard shows as "Last run". ``0`` keeps everything.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Run
from app.services import settings_service
from app.timeutil import utcnow

DEFAULT_DAYS = 90


def retention_days() -> int:
    try:
        return max(0, int(settings_service.get("run_retention_days", str(DEFAULT_DAYS))))
    except ValueError:
        return DEFAULT_DAYS


def prune_runs(db: Session, days: int) -> int:
    if days <= 0:
        return 0
    cutoff = utcnow() - timedelta(days=days)
    latest_per_target = db.query(func.max(Run.id)).filter(Run.target_id.isnot(None)).group_by(Run.target_id)
    deleted = (
        db.query(Run)
        .filter(Run.started_at < cutoff, Run.status != "running", Run.id.notin_(latest_per_target))
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


def prune_now() -> None:
    """Scheduler entry point."""
    db = SessionLocal()
    try:
        prune_runs(db, retention_days())
    finally:
        db.close()
