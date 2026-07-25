"""Route smoke tests for the targets CRUD UI (issue #17, PR 3)."""

import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import routes  # noqa: E402
from app.csrf import verify_csrf  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Target  # noqa: E402


def _form(**kw):
    base = {
        "name": "Metal",
        "playlist_id": "PL1",
        "subreddits": "Metal",
        "genre_filter": "",
        "cap": "25",
        "sync_hour": "7",
        "sync_minute": "0",
    }
    base.update(kw)
    return base


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(routes, "is_authenticated", lambda request: True)
    monkeypatch.setattr("app.services.settings_service.is_setup_complete", lambda: True)
    # Skip the network subreddit check.
    monkeypatch.setattr(routes.reddit_service, "first_definitive_problem", lambda subs, ua: None)
    app.dependency_overrides[verify_csrf] = lambda: None
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(verify_csrf, None)
    db = SessionLocal()
    db.query(Target).delete()
    db.commit()
    db.close()


def _first_target_id():
    db = SessionLocal()
    try:
        return db.query(Target).order_by(Target.id.desc()).first().id
    finally:
        db.close()


def test_create_then_list(client):
    r = client.post("/admin/targets", data=_form(), follow_redirects=False)
    assert r.status_code == 303
    page = client.get("/admin/targets")
    assert "Metal" in page.text and "PL1" in page.text


def test_create_requires_subreddit(client):
    r = client.post("/admin/targets", data=_form(subreddits=""), follow_redirects=False)
    assert r.status_code == 400
    assert "at least one subreddit" in r.text


def test_edit_updates_fields(client):
    client.post("/admin/targets", data=_form(name="A"))
    tid = _first_target_id()
    r = client.post(f"/admin/targets/{tid}", data=_form(name="B", cap="10"), follow_redirects=False)
    assert r.status_code == 303
    db = SessionLocal()
    try:
        t = db.get(Target, tid)
        assert t.name == "B" and t.cap == 10
    finally:
        db.close()


def test_toggle_and_delete(client):
    client.post("/admin/targets", data=_form())
    tid = _first_target_id()
    client.post(f"/admin/targets/{tid}/toggle")
    db = SessionLocal()
    assert db.get(Target, tid).enabled is False
    db.close()
    client.post(f"/admin/targets/{tid}/delete")
    db = SessionLocal()
    assert db.get(Target, tid) is None
    db.close()


def test_blocklist_remove(client):
    client.post("/admin/targets", data=_form())
    tid = _first_target_id()
    db = SessionLocal()
    t = db.get(Target, tid)
    t.blocklist_ids = "X,Y,Z"
    db.commit()
    db.close()

    r = client.post(f"/admin/targets/{tid}/blocklist/remove", data={"track_id": "Y"}, follow_redirects=False)
    assert r.status_code == 303
    db = SessionLocal()
    try:
        assert db.get(Target, tid).blocklist_ids == "X,Z"  # only Y removed
    finally:
        db.close()


def test_csrf_required(monkeypatch):
    # Without the verify_csrf override, a POST with no token is rejected.
    monkeypatch.setattr(routes, "is_authenticated", lambda request: True)
    monkeypatch.setattr("app.services.settings_service.is_setup_complete", lambda: True)
    with TestClient(app) as c:
        r = c.post("/admin/targets", data=_form(), follow_redirects=False)
        assert r.status_code == 403
