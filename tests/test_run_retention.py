"""Old run history is pruned, but never a playlist's latest run."""

import os
import tempfile
from datetime import timedelta

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")

import pytest  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Run  # noqa: E402
from app.services import run_retention  # noqa: E402
from app.timeutil import utcnow  # noqa: E402

Base.metadata.create_all(bind=engine)


@pytest.fixture
def db():
    session = SessionLocal()
    session.query(Run).delete()
    session.commit()
    yield session
    session.close()


def _run(db, days_ago, target_id=1, status="success"):
    run = Run(
        status=status, trigger_type="scheduled", target_id=target_id, started_at=utcnow() - timedelta(days=days_ago)
    )
    db.add(run)
    db.commit()
    return run.id


def test_prunes_old_runs_but_keeps_each_targets_latest(db):
    old = _run(db, 200, target_id=1)
    recent = _run(db, 5, target_id=1)
    only_run_of_t2 = _run(db, 300, target_id=2)  # old, but it's what the dashboard shows
    legacy = _run(db, 400, target_id=None)

    assert run_retention.prune_runs(db, days=90) == 2
    remaining = {r.id for r in db.query(Run).all()}
    assert remaining == {recent, only_run_of_t2}
    assert old not in remaining and legacy not in remaining


def test_zero_keeps_everything(db):
    _run(db, 1000)
    _run(db, 2000)
    assert run_retention.prune_runs(db, days=0) == 0
    assert db.query(Run).count() == 2


def test_never_deletes_a_run_in_progress(db):
    stuck = _run(db, 200, status="running")
    _run(db, 1, target_id=1)  # newer run, so `stuck` isn't the latest
    run_retention.prune_runs(db, days=90)
    assert db.get(Run, stuck) is not None


def test_bad_setting_falls_back_to_default(monkeypatch):
    monkeypatch.setattr(run_retention.settings_service, "get", lambda k, d="": "lots")
    assert run_retention.retention_days() == run_retention.DEFAULT_DAYS
