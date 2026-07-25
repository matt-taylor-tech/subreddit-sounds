"""Optional failure notifications via a generic outgoing webhook.

When ``notify_webhook_url`` is configured, a failed sync run POSTs a small JSON
payload to it. The payload carries the same human-readable message under both
``content`` (Discord) and ``text`` (Slack) keys, plus structured fields, so it
works out of the box with the common chat/webhook receivers (Discord, Slack,
ntfy, Apprise). No URL configured means notifications are a no-op.

Sending is strictly best-effort: any failure to notify is swallowed so it can
never affect the sync itself.
"""

from __future__ import annotations

import httpx

from app.services import settings_service


def _webhook_url() -> str:
    return settings_service.get("notify_webhook_url", "").strip()


def is_configured() -> bool:
    return bool(_webhook_url())


def notify_run_failed(run) -> None:
    """POST a failure notification for ``run`` if a webhook is configured.

    Best-effort: never raises. ``run`` is a ``Run`` model instance (only its
    id / trigger_type / message are read), so this stays decoupled from the DB.
    """
    url = _webhook_url()
    if not url:
        return

    message = (
        f"⚠️ subreddit-sounds: sync run #{run.id} FAILED\n"
        f"{run.message or 'no error message'}\n"
        f"(trigger: {run.trigger_type})"
    )
    payload = {
        # Same text under both keys so Discord and Slack both render it.
        "content": message,
        "text": message,
        # Structured fields for generic/JSON consumers.
        "event": "sync_failed",
        "run_id": run.id,
        "status": run.status,
        "trigger": run.trigger_type,
        "message": run.message,
    }
    try:
        with httpx.Client(timeout=10) as client:
            client.post(url, json=payload)
    except Exception:
        # A notification must never break the sync.
        pass
