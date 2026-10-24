import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.db import SessionLocal
from app.services import run_retention, settings_service, targets_service, update_service
from app.services.sync_service import SyncService
from app.timezones import is_valid_timezone

_JOB_PREFIX = "target_"
_UPDATE_JOB = "update_check"
_RETENTION_JOB = "run_retention"
_log = logging.getLogger(__name__)


class SchedulerManager:
    def __init__(self, sync_service: SyncService) -> None:
        self.sync_service = sync_service
        self.scheduler = BackgroundScheduler(timezone="UTC")

    def start(self) -> None:
        """Schedule per-target jobs if setup has been completed."""
        if not self.scheduler.running:
            self.scheduler.start()
        # First tick a minute after boot, off the startup path. The job no-ops
        # until setup is done, when disabled, or when the cache is fresh.
        self.scheduler.add_job(
            update_service.maybe_check,
            trigger=IntervalTrigger(hours=6),
            id=_UPDATE_JOB,
            next_run_time=datetime.now(UTC) + timedelta(minutes=1),
            replace_existing=True,
        )
        self.scheduler.add_job(
            run_retention.prune_now,
            trigger=IntervalTrigger(hours=24),
            id=_RETENTION_JOB,
            next_run_time=datetime.now(UTC) + timedelta(minutes=2),
            replace_existing=True,
        )
        if not settings_service.is_setup_complete():
            return
        self._apply_schedule()

    def reschedule(self) -> None:
        """Re-read targets + global schedule settings and reconcile the jobs.

        Called after setup and on any target CRUD so the scheduler tracks the
        current set of targets and their times without a restart.
        """
        if not self.scheduler.running:
            self.scheduler.start()
        self._apply_schedule()

    def _apply_schedule(self) -> None:
        # Drop the legacy single-job id from before per-target scheduling.
        if self.scheduler.get_job("daily_sync"):
            self.scheduler.remove_job("daily_sync")

        sync_enabled = settings_service.get("sync_enabled", "true").lower() == "true"
        db = SessionLocal()
        try:
            targets = targets_service.list_targets(db, enabled_only=True) if sync_enabled else []
        finally:
            db.close()

        desired = {f"{_JOB_PREFIX}{t.id}": t for t in targets}
        # Remove jobs for targets that are gone or disabled.
        for job in self.scheduler.get_jobs():
            if job.id.startswith(_JOB_PREFIX) and job.id not in desired:
                self.scheduler.remove_job(job.id)

        if not sync_enabled:
            return

        # This runs at startup, so a bad stored value (e.g. from an imported
        # config) must degrade to "that job isn't scheduled", never stop the app
        # from booting. The forms validate too; this is the backstop.
        timezone = settings_service.get("sync_timezone", "America/New_York")
        if not is_valid_timezone(timezone):
            _log.error("Unknown sync_timezone %r; scheduling in UTC until it is fixed in Settings", timezone)
            timezone = "UTC"
        for job_id, target in desired.items():
            try:
                trigger = CronTrigger(hour=target.sync_hour, minute=target.sync_minute, timezone=timezone)
            except ValueError as exc:
                _log.error("Not scheduling target %s (%s): %s", target.id, target.name, exc)
                if self.scheduler.get_job(job_id):
                    self.scheduler.remove_job(job_id)
                continue
            self.scheduler.add_job(
                self._scheduled_job, trigger=trigger, args=[target.id], id=job_id, replace_existing=True
            )

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def next_run(self, target_id: int | None = None) -> datetime | None:
        """Next run for a target, or (no arg) the soonest across all targets."""
        if target_id is not None:
            job = self.scheduler.get_job(f"{_JOB_PREFIX}{target_id}")
            return job.next_run_time if job else None
        times = [j.next_run_time for j in self.scheduler.get_jobs() if j.id.startswith(_JOB_PREFIX) and j.next_run_time]
        return min(times) if times else None

    def next_runs(self) -> dict[int, datetime]:
        """Map of target id -> next scheduled run, for the dashboard."""
        out: dict[int, datetime] = {}
        for job in self.scheduler.get_jobs():
            if job.id.startswith(_JOB_PREFIX) and job.next_run_time:
                out[int(job.id[len(_JOB_PREFIX) :])] = job.next_run_time
        return out

    def _scheduled_job(self, target_id: int) -> None:
        db = SessionLocal()
        try:
            target = targets_service.get_target(db, target_id)
            if target is None or not target.enabled:
                return  # target was deleted/disabled between scheduling and firing
            self.sync_service.run_once(db=db, target=target, trigger_type="scheduled", dry_run=False)
        finally:
            db.close()
