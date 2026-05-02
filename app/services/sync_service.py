from datetime import datetime
from threading import Lock

from sqlalchemy.orm import Session

from app.models import Run


class SyncService:
    def __init__(self) -> None:
        self._lock = Lock()

    def run_once(self, db: Session, trigger_type: str, dry_run: bool = False) -> int | None:
        if not self._lock.acquire(blocking=False):
            return None

        run = Run(trigger_type=trigger_type, dry_run=dry_run, status="running")
        db.add(run)
        db.commit()
        db.refresh(run)

        try:
            # Initial implementation stub: API integrations are wired in next iterations.
            run.added_count = 0
            run.removed_count = 0
            run.low_confidence_count = 0
            run.message = "Sync scaffold executed successfully"
            run.status = "success"
        except Exception as exc:  # noqa: BLE001
            run.status = "failed"
            run.message = f"{type(exc).__name__}: {exc}"
        finally:
            run.ended_at = datetime.utcnow()
            db.add(run)
            db.commit()
            self._lock.release()

        return run.id
