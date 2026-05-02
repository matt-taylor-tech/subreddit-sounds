from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.db import SessionLocal
from app.services.sync_service import SyncService


class SchedulerManager:
    def __init__(self, sync_service: SyncService) -> None:
        self.sync_service = sync_service
        self.scheduler = BackgroundScheduler(timezone=settings.sync_timezone)

    def start(self) -> None:
        if not settings.sync_enabled:
            return

        trigger = CronTrigger(
            hour=settings.sync_hour,
            minute=settings.sync_minute,
            timezone=settings.sync_timezone,
        )
        self.scheduler.add_job(self._scheduled_job, trigger=trigger, id="daily_sync", replace_existing=True)
        self.scheduler.start()

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def next_run(self) -> datetime | None:
        job = self.scheduler.get_job("daily_sync")
        return job.next_run_time if job else None

    def _scheduled_job(self) -> None:
        db = SessionLocal()
        try:
            self.sync_service.run_once(db=db, trigger_type="scheduled", dry_run=False)
        finally:
            db.close()
