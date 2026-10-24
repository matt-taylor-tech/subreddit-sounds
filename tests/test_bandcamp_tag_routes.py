"""Save-time tag validation on the target form.

The form hard-blocks a tag Bandcamp definitively doesn't have, and stores the
canonical slug rather than what was typed. Editing an existing target
must not re-check tags it already had, so a legacy value stays editable.
"""

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
from app.services import bandcamp_service  # noqa: E402


def _form(**kw):
    base = {
        "name": "Metal",
        "playlist_id": "PL1",
        "subreddits": "Metal",
        "genre_filter": "",
        "cap": "25",
        "sync_hour": "7",
        "sync_minute": "0",
        "bandcamp_enabled": "true",
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


def _stub_check(monkeypatch, module, resolver):
    """Stub check_tag on the service the module under test imported."""
    monkeypatch.setattr(module.bandcamp_service, "check_tag", resolver)


def _found(slug):
    return bandcamp_service.TagCheck(True, "ok", "ok", slug=slug)


def _missing(tag):
    return bandcamp_service.TagCheck(False, "not_found", f"'{tag}' isn't a Bandcamp tag.")


def _latest_target():
    db = SessionLocal()
    try:
        return db.query(Target).order_by(Target.id.desc()).first()
    finally:
        db.close()


def test_create_blocks_unknown_tag(client, monkeypatch):
    _stub_check(monkeypatch, routes, lambda tag: _missing(tag))
    r = client.post("/admin/targets", data=_form(bandcamp_tags="notatag"), follow_redirects=False)
    assert r.status_code == 400
    assert "isn&#39;t a Bandcamp tag" in r.text or "isn't a Bandcamp tag" in r.text
    assert _latest_target() is None  # nothing saved


def test_create_stores_canonical_slug(client, monkeypatch):
    _stub_check(monkeypatch, routes, lambda tag: _found("post-rock"))
    r = client.post("/admin/targets", data=_form(bandcamp_tags="Post Rock"), follow_redirects=False)
    assert r.status_code == 303
    target = _latest_target()
    assert target.bandcamp_tags == "post-rock"
    assert target.bandcamp_enabled_tags == "post-rock"


def test_taxonomy_tags_save_without_touching_the_network(client, monkeypatch):
    # Real check_tag, but the tag-index lookup blows up: picking from the picker
    # must save on the taxonomy fast path alone.
    def _boom(slug):
        raise AssertionError(f"no lookup should happen for taxonomy slug {slug}")

    monkeypatch.setattr(bandcamp_service, "_fetch_tag_matches", _boom)
    r = client.post("/admin/targets", data=_form(bandcamp_tags="post-rock, math-rock"), follow_redirects=False)
    assert r.status_code == 303
    assert _latest_target().bandcamp_tags == "post-rock, math-rock"


def test_edit_does_not_recheck_existing_tags(client, monkeypatch):
    _stub_check(monkeypatch, routes, lambda tag: _found("post-rock"))
    client.post("/admin/targets", data=_form(bandcamp_tags="post-rock"))
    target = _latest_target()
    db = SessionLocal()
    stored = db.get(Target, target.id)
    stored.bandcamp_tags = "some-legacy-tag"  # saved before the tag went away
    db.commit()
    db.close()

    # Any lookup now fails definitively; the legacy tag must still survive a save.
    _stub_check(monkeypatch, routes, lambda tag: _missing(tag))
    r = client.post(
        f"/admin/targets/{target.id}",
        data=_form(name="Renamed", bandcamp_tags="some-legacy-tag"),
        follow_redirects=False,
    )
    assert r.status_code == 303
    db = SessionLocal()
    try:
        refreshed = db.get(Target, target.id)
        assert refreshed.name == "Renamed"
        assert refreshed.bandcamp_tags == "some-legacy-tag"
    finally:
        db.close()


def test_edit_blocks_a_newly_added_bad_tag(client, monkeypatch):
    _stub_check(monkeypatch, routes, lambda tag: _found("post-rock"))
    client.post("/admin/targets", data=_form(bandcamp_tags="post-rock"))
    target = _latest_target()

    _stub_check(monkeypatch, routes, lambda tag: _missing(tag))
    r = client.post(
        f"/admin/targets/{target.id}",
        data=_form(bandcamp_tags="post-rock, notatag"),
        follow_redirects=False,
    )
    assert r.status_code == 400
    db = SessionLocal()
    try:
        assert db.get(Target, target.id).bandcamp_tags == "post-rock"  # unchanged
    finally:
        db.close()
