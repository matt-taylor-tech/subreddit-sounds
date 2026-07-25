from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db import SessionLocal
from app.services import settings_service
from app.services.sync_service import SyncService


class SchedulerManager:
    def __init__(self, sync_service: SyncService) -> None:
        self.sync_service = sync_service
        self.scheduler = BackgroundScheduler(timezone="UTC")

    def start(self) -> None:
        """Schedule the daily job if setup has been completed."""
        if not self.scheduler.running:
            self.scheduler.start()
        if not settings_service.is_setup_complete():
            return
        self._apply_schedule()

    def reschedule(self) -> None:
        """Re-read sync settings from DB and (re)add the daily job.

        Called after the setup wizard completes so the scheduler picks up
        the user-configured time without requiring a container restart.
        """
        if not self.scheduler.running:
            self.scheduler.start()
        self._apply_schedule()

    def _apply_schedule(self) -> None:
        sync_enabled = settings_service.get("sync_enabled", "true").lower() == "true"
        if not sync_enabled:
            return
        timezone = settings_service.get("sync_timezone", "America/New_York")
        hour = int(settings_service.get("sync_hour", "7"))
        minute = int(settings_service.get("sync_minute", "0"))
        trigger = CronTrigger(hour=hour, minute=minute, timezone=timezone)
        self.scheduler.add_job(self._scheduled_job, trigger=trigger, id="daily_sync", replace_existing=True)

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def next_run(self) -> datetime | None:
        job = self.scheduler.get_job("daily_sync")
        return job.next_run_time if job else None

    def _scheduled_job(self) -> None:
        db = SessionLocal()
        try:
            self.sync_service.run_all(db=db, trigger_type="scheduled", dry_run=False)
        finally:
            db.close()
