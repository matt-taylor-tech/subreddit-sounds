"""Update-available check (issue #41, phase 2)."""

import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import routes  # noqa: E402
from app.auth import hash_password  # noqa: E402
from app.csrf import verify_csrf  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AppSetting  # noqa: E402
from app.services import settings_service, update_service  # noqa: E402

Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    db = SessionLocal()
    db.query(AppSetting).delete()
    db.commit()
    db.close()
    monkeypatch.setattr(update_service, "get_version", lambda: "0.1.1")


class _Resp:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self._data = data

    def json(self):
        return self._data


def _fake_github(monkeypatch, status_code=200, data=None, boom=False):
    calls = []

    class _Client:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url, **kw):
            calls.append(url)
            if boom:
                raise OSError("offline")
            return _Resp(status_code, data or {})

    monkeypatch.setattr(update_service.httpx, "Client", _Client)
    return calls


def test_version_comparison():
    assert update_service.is_newer("0.2.0", "0.1.1")
    assert update_service.is_newer("v0.1.10", "0.1.9")  # numeric, not lexical
    assert not update_service.is_newer("0.1.1", "0.1.1")
    assert not update_service.is_newer("0.1.0", "0.1.1")
    assert not update_service.is_newer("0.2.0", "unknown")
    assert not update_service.is_newer("nightly", "0.1.1")


def test_check_caches_a_newer_release(monkeypatch):
    _fake_github(monkeypatch, data={"tag_name": "v0.2.0", "html_url": "https://example/rel"})
    update_service.check_now()
    assert update_service.available_update() == {"version": "0.2.0", "url": "https://example/rel", "dismissed": False}


def test_check_fails_silently_and_keeps_the_old_cache(monkeypatch):
    settings_service.put("update_latest_version", "0.2.0")
    _fake_github(monkeypatch, boom=True)
    update_service.check_now()  # must not raise
    _fake_github(monkeypatch, status_code=403, data={"message": "rate limited"})
    update_service.check_now()
    assert settings_service.get("update_latest_version") == "0.2.0"


def test_maybe_check_is_throttled_and_respects_the_toggle(monkeypatch):
    monkeypatch.setattr(update_service.settings_service, "is_setup_complete", lambda: True)
    calls = _fake_github(monkeypatch, data={"tag_name": "v0.2.0"})
    update_service.maybe_check()
    update_service.maybe_check()  # cache is fresh now
    assert len(calls) == 1

    settings_service.put("update_last_check", "0")
    settings_service.put("update_check_enabled", "false")
    update_service.maybe_check()
    assert len(calls) == 1
    assert update_service.available_update() is None  # disabled hides the notice too


def test_maybe_check_waits_for_setup(monkeypatch):
    monkeypatch.setattr(update_service.settings_service, "is_setup_complete", lambda: False)
    calls = _fake_github(monkeypatch, data={"tag_name": "v0.2.0"})
    update_service.maybe_check()
    assert calls == []


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(routes.spotify_service, "is_connected", lambda: False)
    app.dependency_overrides[verify_csrf] = lambda: None
    with TestClient(app) as c:
        # A real sign-in: the banner is keyed off the session flag, as the nav is.
        settings_service.put_many({"admin_username": "admin", "admin_password_hash": hash_password("pw")})
        assert c.post("/login", data={"username": "admin", "password": "pw"}, follow_redirects=False).status_code == 303
        yield c
    app.dependency_overrides.pop(verify_csrf, None)


def test_banner_shows_until_dismissed(client):
    settings_service.put_many({"update_latest_version": "0.2.0", "update_latest_url": "https://example/rel"})
    page = client.get("/admin/settings").text
    assert "v0.2.0 is out" in page
    assert "v0.2.0 available" in page  # footer badge

    r = client.post("/admin/update/dismiss", follow_redirects=False)
    assert r.status_code == 303
    page = client.get("/admin/settings").text
    assert "v0.2.0 is out" not in page
    assert "v0.2.0 available" in page  # the quiet footer link stays


def test_no_banner_when_up_to_date(client):
    settings_service.put("update_latest_version", "0.1.1")
    page = client.get("/admin/settings").text
    assert "is out" not in page and "available</a>" not in page
