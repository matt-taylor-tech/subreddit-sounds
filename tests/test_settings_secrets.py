"""Stored secrets must never be echoed back into the Settings page.

The save handler treats a blank secret field as "keep the existing value", so
pre-filling the input gained nothing and put live credentials into the page
source, the browser cache, and any screenshot of that page.
"""

import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import routes  # noqa: E402
from app.csrf import verify_csrf  # noqa: E402
from app.main import app  # noqa: E402
from app.services import settings_service  # noqa: E402

_SPOTIFY_SECRET = "spotify-secret-do-not-render"
_REDDIT_SECRET = "reddit-secret-do-not-render"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(routes, "is_authenticated", lambda request: True)
    monkeypatch.setattr("app.services.settings_service.is_setup_complete", lambda: True)
    app.dependency_overrides[verify_csrf] = lambda: None
    with TestClient(app) as c:
        settings_service.put_many(
            {
                "spotify_client_id": "cid",
                "spotify_client_secret": _SPOTIFY_SECRET,
                "reddit_client_secret": _REDDIT_SECRET,
            }
        )
        yield c
    app.dependency_overrides.pop(verify_csrf, None)


def test_settings_page_never_contains_a_stored_secret(client):
    body = client.get("/admin/settings").text
    assert _SPOTIFY_SECRET not in body
    assert _REDDIT_SECRET not in body


def test_secret_fields_are_masked_and_marked_as_stored(client):
    body = client.get("/admin/settings").text
    assert 'id="spotify_client_secret" name="spotify_client_secret" type="password"' in body
    assert 'id="reddit_client_secret" name="reddit_client_secret" type="password"' in body
    # The user still needs to know a secret exists without being shown it.
    assert "stored, leave blank to keep it" in body


def test_blank_secret_keeps_the_stored_value(client):
    """The masked field posts blank on every save, so blank must not wipe it."""
    form = {
        "reddit_sort": "top",
        "reddit_timeframe": "week",
        "reddit_user_agent": "ua",
        "reddit_client_id": "",
        "reddit_client_secret": "",
        "min_track_duration_sec": "120",
        "sync_timezone": "UTC",
        "spotify_client_id": "cid",
        "spotify_client_secret": "",
        "spotify_redirect_uri": "http://127.0.0.1:8000/callback",
        "notify_webhook_url": "",
    }
    r = client.post("/admin/settings", data=form, follow_redirects=False)
    assert r.status_code in (200, 303)
    assert settings_service.get("spotify_client_secret") == _SPOTIFY_SECRET
    assert settings_service.get("reddit_client_secret") == _REDDIT_SECRET


def test_a_new_secret_still_replaces_the_old_one(client):
    form = {
        "reddit_sort": "top",
        "reddit_timeframe": "week",
        "reddit_user_agent": "ua",
        "reddit_client_id": "",
        "reddit_client_secret": "",
        "min_track_duration_sec": "120",
        "sync_timezone": "UTC",
        "spotify_client_id": "cid",
        "spotify_client_secret": "rotated-secret",
        "spotify_redirect_uri": "http://127.0.0.1:8000/callback",
        "notify_webhook_url": "",
    }
    client.post("/admin/settings", data=form, follow_redirects=False)
    assert settings_service.get("spotify_client_secret") == "rotated-secret"
