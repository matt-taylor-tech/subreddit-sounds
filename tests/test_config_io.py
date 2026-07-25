"""Import / export of config (issue #48)."""

import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")

import pytest  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import AppSetting, Target  # noqa: E402
from app.services import config_io, settings_service, targets_service  # noqa: E402

Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean():
    db = SessionLocal()
    db.query(Target).delete()
    db.query(AppSetting).delete()
    db.commit()
    db.close()


def _seed(db):
    settings_service.put_many(
        {
            "reddit_sort": "top",
            "sync_timezone": "UTC",
            "spotify_client_secret": "SECRET",  # is_secret via _SECRET_KEYS
            "admin_password_hash": "HASH",  # is_secret
        }
    )
    targets_service.create_target(db, name="Metal", playlist_id="P1", subreddits="Metal", cap=30)


def test_export_excludes_secrets_by_default():
    db = SessionLocal()
    try:
        _seed(db)
        data = config_io.export_config(db)
        assert data["settings"]["reddit_sort"] == "top"
        assert "spotify_client_secret" not in data["settings"]
        assert "admin_password_hash" not in data["settings"]
        assert len(data["targets"]) == 1 and data["targets"][0]["name"] == "Metal"
    finally:
        db.close()


def test_export_includes_secrets_when_opted_in():
    db = SessionLocal()
    try:
        _seed(db)
        data = config_io.export_config(db, include_secrets=True)
        assert data["settings"]["spotify_client_secret"] == "SECRET"
        assert data["settings"]["admin_password_hash"] == "HASH"
    finally:
        db.close()


def test_import_restores_and_replaces_targets():
    db = SessionLocal()
    try:
        _seed(db)
        exported = config_io.export_config(db)
        # Mutate state: extra target + changed setting.
        targets_service.create_target(db, name="Extra", playlist_id="PX", subreddits="x")
        settings_service.put_many({"reddit_sort": "hot"})

        config_io.import_config(db, exported)

        names = [t.name for t in targets_service.list_targets(db)]
        assert names == ["Metal"]  # replaced (Extra gone)
        assert settings_service.get("reddit_sort") == "top"  # restored
    finally:
        db.close()


def test_import_rejects_garbage():
    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            config_io.import_config(db, "not a dict")
        with pytest.raises(ValueError):
            config_io.import_config(db, {"targets": "nope"})
    finally:
        db.close()


def test_import_skips_target_without_playlist_id():
    db = SessionLocal()
    try:
        config_io.import_config(db, {"settings": {}, "targets": [{"name": "no-playlist"}]})
        assert targets_service.list_targets(db) == []
    finally:
        db.close()
