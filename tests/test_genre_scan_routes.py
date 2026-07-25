"""The genre checklist end to end: scan endpoint, then saving the ticked boxes."""

import json
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
        "subreddits": "doommetal",
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
    monkeypatch.setattr(routes.reddit_service, "first_definitive_problem", lambda subs, ua: None)
    app.dependency_overrides[verify_csrf] = lambda: None
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(verify_csrf, None)
    db = SessionLocal()
    db.query(Target).delete()
    db.commit()
    db.close()


def _latest():
    db = SessionLocal()
    try:
        return db.query(Target).order_by(Target.id.desc()).first()
    finally:
        db.close()


def _make_target(client):
    client.post("/admin/targets", data=_form(), follow_redirects=False)
    return _latest().id


def test_ticked_genres_are_saved_as_the_filter(client):
    tid = _make_target(client)
    r = client.post(
        f"/admin/targets/{tid}",
        data=_form(genres=["death metal", "doom metal"], genre_include_substyles="true"),
        follow_redirects=False,
    )
    assert r.status_code == 303
    target = _latest()
    assert target.genre_filter == "death metal, doom metal"
    assert target.genre_include_substyles is True
    assert target.genre_include_unclassified is False  # unticked checkbox posts nothing


def test_unticking_everything_clears_the_filter(client):
    tid = _make_target(client)
    client.post(f"/admin/targets/{tid}", data=_form(genres=["death metal"]))
    assert _latest().genre_filter == "death metal"
    client.post(f"/admin/targets/{tid}", data=_form())
    assert _latest().genre_filter is None


def test_scan_stores_the_result_and_renders_the_checklist(client, monkeypatch):
    tid = _make_target(client)
    payload = {
        "genres": [{"name": "death metal", "count": 7}, {"name": "doom metal", "count": 2}],
        "unclassified": 4,
        "resolved": 13,
        "posts": 40,
        "subreddits": ["doommetal"],
        "scanned_at": "2026-07-25T16:00:00",
    }
    monkeypatch.setattr(routes.genre_scan_service, "scan_target", lambda target: payload)

    r = client.post(f"/admin/targets/{tid}/scan-genres", follow_redirects=False)
    assert r.status_code == 303
    assert json.loads(_latest().genre_scan)["resolved"] == 13

    page = client.get(f"/admin/targets/{tid}/edit")
    assert "death metal" in page.text
    assert "doom metal" in page.text
    assert 'name="genres"' in page.text
    assert "4 in the last scan" in page.text  # unclassified count surfaced


def test_scan_failure_reports_instead_of_500(client, monkeypatch):
    tid = _make_target(client)

    def _boom(target):
        raise RuntimeError("Connect Spotify from the dashboard before scanning for genres.")

    monkeypatch.setattr(routes.genre_scan_service, "scan_target", _boom)
    r = client.post(f"/admin/targets/{tid}/scan-genres", follow_redirects=True)
    assert r.status_code == 200
    assert "Connect Spotify" in r.text
    assert _latest().genre_scan == ""  # nothing stored on failure


def test_scan_button_belongs_to_its_own_form(client):
    """Enter in a text field must save, not scan.

    A form's implicit-submit button is the first submit control it *owns*, so the
    scan button has to be owned by a separate form via the `form` attribute.
    Otherwise pressing Enter anywhere on the page triggers a scan and discards
    the edit.
    """
    tid = _make_target(client)
    page = client.get(f"/admin/targets/{tid}/edit")
    assert 'form="scan-form"' in page.text
    assert f'<form id="scan-form" method="post" action="/admin/targets/{tid}/scan-genres"' in page.text
    # The old formaction approach would have made it the main form's default.
    assert "formaction" not in page.text


def test_new_target_form_tells_you_to_save_before_scanning(client):
    page = client.get("/admin/targets/new")
    assert "Save the playlist first" in page.text
    assert "scan-genres" not in page.text  # no scan button until it exists
