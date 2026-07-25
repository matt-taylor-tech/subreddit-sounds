"""The manual-run form: Preview submits a dry run, Run Now submits a real run.

Covers both the route wiring (which dry_run value each button sends to
SyncService.run_once) and the runs template (both buttons present, and the
just-triggered run's log auto-expands so the preview is surfaced).
"""

import os
import tempfile
from types import SimpleNamespace

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")

from fastapi.testclient import TestClient  # noqa: E402
from jinja2 import Environment, FileSystemLoader  # noqa: E402

from app import routes  # noqa: E402
from app.csrf import verify_csrf  # noqa: E402
from app.main import app  # noqa: E402


class _FakeSync:
    def __init__(self):
        self.calls = []

    def run_once(self, db, trigger_type, dry_run=False):
        self.calls.append((trigger_type, dry_run))
        return 123


def _run(monkeypatch, form):
    fake = _FakeSync()
    app.state.sync_service = fake
    monkeypatch.setattr(routes, "is_authenticated", lambda request: True)
    # The SetupRedirectMiddleware queries the DB on every request; bypass it so
    # the test needs no tables and isn't redirected to /setup.
    monkeypatch.setattr("app.services.settings_service.is_setup_complete", lambda: True)
    app.dependency_overrides[verify_csrf] = lambda: None
    try:
        client = TestClient(app)
        resp = client.post("/admin/run", data=form, follow_redirects=False)
    finally:
        app.dependency_overrides.pop(verify_csrf, None)
    return resp, fake


def test_preview_button_triggers_dry_run(monkeypatch):
    resp, fake = _run(monkeypatch, {"dry_run": "true"})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/runs?run_id=123"
    assert fake.calls == [("manual", True)]


def test_run_now_button_is_not_dry_run(monkeypatch):
    resp, fake = _run(monkeypatch, {"dry_run": "false"})
    assert resp.status_code == 303
    assert fake.calls == [("manual", False)]


def test_missing_dry_run_defaults_to_real_run(monkeypatch):
    resp, fake = _run(monkeypatch, {})
    assert resp.status_code == 303
    assert fake.calls == [("manual", False)]


def _render_runs(highlight_run_id):
    env = Environment(loader=FileSystemLoader("app/templates"), autoescape=True)
    req = SimpleNamespace(session={"is_authenticated": True})
    started = SimpleNamespace(strftime=lambda fmt: "2026-07-25 09:00:00")
    run = SimpleNamespace(
        id=5,
        status="success",
        trigger_type="manual",
        dry_run=True,
        started_at=started,
        ended_at=None,
        low_confidence_count=1,
        added_count=0,
        message="[dry] +3 -1",
        log="Tracks to add: 3, to remove: 1\n  + A\n  - B",
    )
    return env.get_template("runs.html").render(
        request=req, csrf_token="tok", runs=[run], highlight_run_id=highlight_run_id
    )


def test_runs_page_has_both_buttons():
    html = _render_runs(highlight_run_id=None)
    assert 'name="dry_run" value="true"' in html
    assert 'name="dry_run" value="false"' in html
    assert "Preview (dry run)" in html
    assert "Run Now" in html


def test_highlighted_run_log_auto_expands():
    # The just-triggered run (id 5) is highlighted -> its <details> opens.
    assert "<details open>" in _render_runs(highlight_run_id=5)
    # A non-highlighted view leaves the log collapsed.
    assert "<details open>" not in _render_runs(highlight_run_id=None)
