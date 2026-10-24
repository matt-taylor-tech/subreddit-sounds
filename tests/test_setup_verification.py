"""Setup wizard: connection settings only, no playlist created.

These drive the POST /setup route with the CSRF dependency overridden and the
settings store monkeypatched, so no network or database is touched.
"""

from fastapi.testclient import TestClient

from app import setup_wizard
from app.csrf import verify_csrf
from app.main import app

_FORM = {
    "admin_username": "admin",
    "admin_password": "pw",
    "admin_password_confirm": "pw",
    "spotify_client_id": "cid",
    "spotify_client_secret": "sec",
}


def _client(monkeypatch):
    """A TestClient with CSRF disabled, setup incomplete, and the store stubbed."""
    saved: dict = {}
    monkeypatch.setattr(setup_wizard.settings_service, "is_setup_complete", lambda: False)
    monkeypatch.setattr(setup_wizard.settings_service, "put_many", lambda pairs: saved.update(pairs))
    app.dependency_overrides[verify_csrf] = lambda: None
    return TestClient(app), saved


def _teardown():
    app.dependency_overrides.pop(verify_csrf, None)


def test_setup_saves_connection_settings_without_a_playlist(monkeypatch):
    client, saved = _client(monkeypatch)
    try:
        r = client.post("/setup", data=_FORM, follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/admin/dashboard"  # signed straight in
        assert saved["spotify_client_id"] == "cid"
        assert saved["sync_timezone"] == "America/New_York"
        assert "spotify_playlist_id" not in saved and "reddit_subreddit" not in saved
    finally:
        _teardown()


def test_setup_rejects_unknown_timezone(monkeypatch):
    client, saved = _client(monkeypatch)
    try:
        r = client.post("/setup", data={**_FORM, "sync_timezone": "Mars/Olympus_Mons"})
        assert r.status_code == 400
        assert "Unknown timezone" in r.text
        assert saved == {}  # nothing persisted
    finally:
        _teardown()


def test_setup_rejects_mismatched_passwords(monkeypatch):
    client, saved = _client(monkeypatch)
    try:
        r = client.post("/setup", data={**_FORM, "admin_password_confirm": "other"})
        assert r.status_code == 400
        assert saved == {}
    finally:
        _teardown()
