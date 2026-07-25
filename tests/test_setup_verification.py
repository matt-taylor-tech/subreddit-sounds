"""Setup wizard: the subreddit is verified before the config is saved.

These drive the POST /setup route with the CSRF dependency overridden and the
DB / Reddit calls monkeypatched, so no network or database is touched. They
confirm the hard-block rule: a *definitive* bad-subreddit result stops the save,
while an ambiguous one (rate-limit / IP block) is allowed through.
"""

from fastapi.testclient import TestClient

from app import setup_wizard
from app.csrf import verify_csrf
from app.main import app
from app.services import reddit_service

_FORM = {
    "admin_username": "admin",
    "admin_password": "pw",
    "admin_password_confirm": "pw",
    "reddit_subreddit": "SomeSub",
    "spotify_client_id": "cid",
    "spotify_client_secret": "sec",
    "spotify_playlist_id": "pl",
}


def _client(monkeypatch, *, check_result):
    """A TestClient with CSRF disabled, setup incomplete, and reddit/DB stubbed."""
    saved: dict = {}
    created: dict = {}
    monkeypatch.setattr(setup_wizard.settings_service, "is_setup_complete", lambda: False)
    monkeypatch.setattr(setup_wizard.settings_service, "put_many", lambda pairs: saved.update(pairs))
    monkeypatch.setattr(setup_wizard.reddit_service, "check_subreddit", lambda sub, ua: check_result)
    monkeypatch.setattr(setup_wizard.targets_service, "create_target", lambda db, **fields: created.update(fields))
    app.dependency_overrides[verify_csrf] = lambda: None
    client = TestClient(app)
    return client, saved, created


def _teardown():
    app.dependency_overrides.pop(verify_csrf, None)


def test_setup_blocks_on_definitive_bad_subreddit(monkeypatch):
    bad = reddit_service.SubredditCheck(False, "not_found", "r/SomeSub doesn't exist (404).", definitive=True)
    client, saved, created = _client(monkeypatch, check_result=bad)
    try:
        r = client.post("/setup", data=_FORM)
        assert r.status_code == 400
        assert "doesn&#39;t exist" in r.text or "doesn't exist" in r.text
        assert saved == {} and created == {}  # nothing persisted, no target created
    finally:
        _teardown()


def test_setup_allows_when_verification_confirms_readable(monkeypatch):
    ok = reddit_service.SubredditCheck(True, "ok", "r/SomeSub exists and is readable.", definitive=True)
    client, saved, created = _client(monkeypatch, check_result=ok)
    try:
        r = client.post("/setup", data=_FORM, follow_redirects=False)
        assert r.status_code == 303  # redirect to /login on success
        assert created["subreddits"] == "SomeSub"  # first target created from the wizard
        assert created["playlist_id"] == "pl"
    finally:
        _teardown()


def test_setup_allows_on_ambiguous_result(monkeypatch):
    # A rate-limit / IP-block can't confirm the sub is bad; the save proceeds.
    ambiguous = reddit_service.SubredditCheck(
        False, "rate_limited", "Couldn't verify r/SomeSub (429).", definitive=False
    )
    client, saved, created = _client(monkeypatch, check_result=ambiguous)
    try:
        r = client.post("/setup", data=_FORM, follow_redirects=False)
        assert r.status_code == 303
        assert created["subreddits"] == "SomeSub"
    finally:
        _teardown()
