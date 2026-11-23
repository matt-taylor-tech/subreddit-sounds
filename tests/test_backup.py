"""Full backups (#74): round trip, refusing unsafe files, and restore at setup."""

import json
import os
import sqlite3
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import setup_wizard  # noqa: E402
from app.csrf import verify_csrf  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AppSetting, ResolvedLink, Run, Target  # noqa: E402
from app.services import backup_service, config_io  # noqa: E402

Base.metadata.create_all(bind=engine)


def _wipe(db):
    for model in (Run, ResolvedLink, Target, AppSetting):
        db.query(model).delete()
    db.commit()


@pytest.fixture
def db():
    session = SessionLocal()
    _wipe(session)
    yield session
    _wipe(session)
    session.close()


def _seed(db):
    db.add(AppSetting(key="admin_password_hash", value="HASH", is_secret=True))
    db.add(AppSetting(key="spotify_refresh_token", value="RT", is_secret=True))
    db.add(Target(name="Metal", playlist_id="P1", subreddits="Metal", blocklist_ids="a,b"))
    db.add(Run(status="success", trigger_type="scheduled"))
    db.add(ResolvedLink(key="k" * 64, track_id="T1", detail="Song"))
    db.commit()


def test_full_backup_round_trip_keeps_everything(db):
    _seed(db)
    raw = backup_service.make_backup()
    assert raw.startswith(b"SQLite format 3\x00")

    _wipe(db)
    summary = backup_service.restore(raw, db)

    assert summary["playlists"] == 1 and summary["blocked_tracks"] == 2
    assert summary["runs"] == 1 and summary["cached_matches"] == 1
    assert summary["has_admin"] and summary["has_spotify"]


def test_restore_still_accepts_a_json_settings_export(db):
    _seed(db)
    exported = json.dumps(config_io.export_config(db, include_secrets=False)).encode()
    _wipe(db)

    summary = backup_service.restore(exported, db)

    assert summary["playlists"] == 1 and summary["blocked_tracks"] == 2
    assert summary["runs"] == 0  # JSON never carried history
    assert summary["has_admin"] is False  # exported without secrets


def _sqlite_file(statements):
    path = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(path)
    for sql in statements:
        conn.execute(sql)
    conn.commit()
    conn.close()
    with open(path, "rb") as f:
        return f.read()


def test_refuses_a_database_with_triggers(db):
    # Copied into the live DB, a trigger would run later inside the app.
    raw = _sqlite_file(
        [
            "CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT, is_secret BOOLEAN, updated_at DATETIME)",
            "CREATE TABLE targets (id INTEGER PRIMARY KEY)",
            "CREATE TRIGGER evil AFTER INSERT ON targets BEGIN DELETE FROM app_settings; END",
        ]
    )
    with pytest.raises(ValueError, match="triggers"):
        backup_service.restore(raw, db)


def test_refuses_an_unrelated_database(db):
    with pytest.raises(ValueError, match="isn't a subreddit-sounds backup"):
        backup_service.restore(_sqlite_file(["CREATE TABLE photos (id INTEGER)"]), db)


def test_refuses_garbage(db):
    with pytest.raises(ValueError, match="neither a full backup"):
        backup_service.restore(b"\x00\x01 not a backup", db)


@pytest.fixture
def setup_client(monkeypatch):
    state = {"complete": False}
    monkeypatch.setattr(setup_wizard.settings_service, "is_setup_complete", lambda: state["complete"])
    app.dependency_overrides[verify_csrf] = lambda: None
    with TestClient(app) as client:
        yield client, state
    app.dependency_overrides.pop(verify_csrf, None)


def test_setup_restore_with_a_full_backup_goes_straight_to_login(db, setup_client):
    client, _ = setup_client
    _seed(db)
    raw = backup_service.make_backup()
    _wipe(db)

    r = client.post("/setup/restore", files={"file": ("backup.db", raw)}, follow_redirects=False)

    assert r.status_code == 303 and r.headers["location"] == "/login?restored=1"
    assert db.query(Target).count() == 1


def test_setup_restore_without_secrets_asks_for_the_rest(db, setup_client):
    client, _ = setup_client
    _seed(db)
    exported = json.dumps(config_io.export_config(db, include_secrets=False)).encode()
    _wipe(db)

    r = client.post("/setup/restore", files={"file": ("settings.json", exported)})

    assert r.status_code == 200
    assert "Restored 1 playlist(s)" in r.text
    assert 'action="/setup"' in r.text  # the wizard is still there to finish


def test_setup_restore_is_closed_once_setup_is_done(db, setup_client):
    client, state = setup_client
    state["complete"] = True
    _seed(db)
    raw = backup_service.make_backup()
    _wipe(db)

    r = client.post("/setup/restore", files={"file": ("backup.db", raw)}, follow_redirects=False)

    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert db.query(Target).count() == 0  # nothing restored
