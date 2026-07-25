"""Per-target scheduling (issue #17, PR 2): one cron job per enabled target,
reconciled on reschedule."""

import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")

import pytest  # noqa: E402

import app.scheduler as sch  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Target  # noqa: E402
from app.services import targets_service  # noqa: E402

Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean_targets():
    db = SessionLocal()
    db.query(Target).delete()
    db.commit()
    db.close()


class _FakeSync:
    pass


def _mgr(monkeypatch, sync_enabled="true", tz="UTC"):
    cfg = {"sync_enabled": sync_enabled, "sync_timezone": tz}
    monkeypatch.setattr(sch.settings_service, "get", lambda k, d="": cfg.get(k, d))
    m = sch.SchedulerManager(_FakeSync())
    m.scheduler.start()
    return m


def _ids(m):
    return {j.id for j in m.scheduler.get_jobs()}


def test_job_per_enabled_target(monkeypatch):
    db = SessionLocal()
    a_id = targets_service.create_target(db, name="A", playlist_id="P1", enabled=True, sync_hour=7).id
    b_id = targets_service.create_target(db, name="B", playlist_id="P2", enabled=True, sync_hour=3).id
    targets_service.create_target(db, name="C", playlist_id="P3", enabled=False)
    db.close()

    m = _mgr(monkeypatch)
    try:
        m._apply_schedule()
        assert _ids(m) == {f"target_{a_id}", f"target_{b_id}"}  # disabled C has no job
    finally:
        m.shutdown()


def test_reschedule_removes_stale_job(monkeypatch):
    db = SessionLocal()
    a_id = targets_service.create_target(db, name="A", playlist_id="P1", enabled=True).id
    b_id = targets_service.create_target(db, name="B", playlist_id="P2", enabled=True).id
    db.close()

    m = _mgr(monkeypatch)
    try:
        m._apply_schedule()
        assert _ids(m) == {f"target_{a_id}", f"target_{b_id}"}
        # Disable B, reschedule -> its job is removed.
        db = SessionLocal()
        targets_service.update_target(db, b_id, enabled=False)
        db.close()
        m._apply_schedule()
        assert _ids(m) == {f"target_{a_id}"}
    finally:
        m.shutdown()


def test_sync_disabled_clears_all_jobs(monkeypatch):
    db = SessionLocal()
    targets_service.create_target(db, name="A", playlist_id="P1", enabled=True)
    db.close()

    m = _mgr(monkeypatch, sync_enabled="false")
    try:
        m._apply_schedule()
        assert _ids(m) == set()
    finally:
        m.shutdown()


def test_scheduled_job_runs_target(monkeypatch):
    db = SessionLocal()
    t = targets_service.create_target(db, name="A", playlist_id="P1", enabled=True)
    db.close()

    calls = []

    class RecordingSync:
        def run_once(self, db, target, trigger_type, dry_run=False):
            calls.append((target.id, trigger_type))
            return 1

    m = sch.SchedulerManager(RecordingSync())
    m._scheduled_job(t.id)
    assert calls == [(t.id, "scheduled")]

    # A disabled/deleted target is a no-op when its job fires.
    db = SessionLocal()
    targets_service.update_target(db, t.id, enabled=False)
    db.close()
    m._scheduled_job(t.id)
    assert calls == [(t.id, "scheduled")]  # unchanged
