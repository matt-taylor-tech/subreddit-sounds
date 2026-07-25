"""Import / export the app config (playlists + global settings) as JSON.

Export defaults to excluding secrets (API client secrets, OAuth tokens, the
admin password hash, the notify webhook) using the ``is_secret`` flag; callers
can opt in to include them. Import replaces the playlist set and applies the
settings, so it is a restore rather than a merge.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services import settings_service, targets_service

FORMAT_VERSION = 1

# Target columns carried in an export (everything needed to recreate a target;
# id/created_at are intentionally omitted).
_TARGET_FIELDS = [
    "name",
    "enabled",
    "playlist_id",
    "subreddits",
    "genre_filter",
    "cap",
    "bandcamp_enabled",
    "bandcamp_tags",
    "bandcamp_enabled_tags",
    "blocklist_enabled",
    "blocklist_ids",
    "last_desired_ids",
    "sync_hour",
    "sync_minute",
]


def export_config(db: Session, include_secrets: bool = False) -> dict:
    """Build the exportable config dict. Secrets are excluded unless opted in."""
    settings = {key: value for key, value, secret in settings_service.all_items() if include_secrets or not secret}
    targets = [{field: getattr(t, field) for field in _TARGET_FIELDS} for t in targets_service.list_targets(db)]
    return {
        "version": FORMAT_VERSION,
        "include_secrets": include_secrets,
        "settings": settings,
        "targets": targets,
    }


def import_config(db: Session, data: dict) -> tuple[int, int]:
    """Restore config from an exported dict. Returns (n_settings, n_targets).

    Applies the settings (put_many tags secret keys via the existing whitelist)
    and **replaces** the playlist set with the imported targets.
    """
    if not isinstance(data, dict):
        raise ValueError("Import file is not a config object.")

    settings = data.get("settings") or {}
    if not isinstance(settings, dict):
        raise ValueError("Import file has an invalid 'settings' section.")
    if settings:
        settings_service.put_many({str(k): str(v) for k, v in settings.items()})

    targets = data.get("targets")
    if targets is not None:
        if not isinstance(targets, list):
            raise ValueError("Import file has an invalid 'targets' section.")
        for existing in targets_service.list_targets(db):
            targets_service.delete_target(db, existing.id)
        for entry in targets:
            fields = {f: entry[f] for f in _TARGET_FIELDS if f in entry}
            if not fields.get("playlist_id"):
                continue  # skip malformed target rows
            targets_service.create_target(db, **fields)

    return len(settings), len(targets or [])
