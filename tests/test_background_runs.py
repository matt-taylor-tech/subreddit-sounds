"""Manual runs execute on a worker thread; the request only waits for the row."""

import os
import tempfile
import threading
import time
from datetime import datetime

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")

import pytest  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Run, Target  # noqa: E402
from app.services import sync_service, targets_service  # noqa: E402
from app.services.sync_service import SyncService, mark_interrupted_runs  # noqa: E402

Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean():
    db = SessionLocal()
    db.query(Run).delete()
    db.query(Target).delete()
    db.commit()
    db.close()


class _SlowSync(SyncService):
    """run_once that creates its row, then blocks until released."""

    def __init__(self):
        super().__init__()
        self.release = threading.Event()
        self.ran: list[int] = []

    def run_once(self, db, target, trigger_type, dry_run=False, on_start=None):
        run = Run(trigger_type=trigger_type, dry_run=dry_run, status="running", target_id=target.id)
        db.add(run)
        db.commit()
        if on_start:
            on_start(run.id)
        self.release.wait(5)
        self.ran.append(target.id)
        run.status = "success"
        db.commit()
        return run.id


def _targets(n):
    db = SessionLocal()
    try:
        return [targets_service.create_target(db, name=f"T{i}", playlist_id=f"P{i}").id for i in range(n)]
    finally:
        db.close()


def test_returns_the_first_run_id_before_the_sync_finishes():
    ids = _targets(2)
    svc = _SlowSync()
    run_id = svc.start_in_background(ids, "manual")
    assert run_id is not None
    assert svc.ran == []  # still in progress: the request didn't wait for it
    svc.release.set()
    # Let the worker finish both targets, or it writes runs into the next test.
    deadline = time.monotonic() + 5
    while len(svc.ran) < len(ids) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert svc.ran == ids


def test_returns_none_when_nothing_started():
    svc = SyncService()
    assert svc.start_in_background([], "manual", wait=1) is None


def test_log_is_written_while_the_run_is_still_going(monkeypatch):
    # Flush on every line, then stop the run partway: the Runs page must
    # already have the lines logged so far.
    monkeypatch.setattr(sync_service, "_LOG_FLUSH_SEC", 0)
    seen: list[str | None] = []

    def fake_fetch(subreddits, user_agent, sort, timeframe, log):
        log("fetched r/Metal")
        check = SessionLocal()
        try:
            seen.append(check.query(Run).filter(Run.target_id == tid).one().log)
        finally:
            check.close()
        raise RuntimeError("stop here")

    monkeypatch.setattr(sync_service, "_fetch_all_posts", fake_fetch)
    (tid,) = _targets(1)
    db = SessionLocal()
    try:
        SyncService().run_once(db, targets_service.get_target(db, tid), "manual")
    finally:
        db.close()
    assert seen and "fetched r/Metal" in seen[0]


def test_restart_fails_runs_left_running():
    db = SessionLocal()
    try:
        db.add(Run(status="running", trigger_type="manual", started_at=datetime(2026, 1, 1)))
        db.add(Run(status="success", trigger_type="manual"))
        db.commit()
        assert mark_interrupted_runs(db) == 1
        statuses = sorted(r.status for r in db.query(Run).all())
        assert statuses == ["failed", "success"]
    finally:
        db.close()
