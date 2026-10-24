"""Optional "a newer release exists" check against GitHub releases.

Runs from the scheduler at most once a day, never on a page load: the result is
cached in ``app_settings`` and templates only read the cache. Any failure
(offline, rate-limited, odd response) is swallowed and simply leaves the old
cache in place. It can be switched off in Settings, since it is an outbound
call to GitHub.
"""

from __future__ import annotations

import re
import time

import httpx
from fastapi import Request

from app.services import settings_service
from app.version import get_version

RELEASES_URL = "https://api.github.com/repos/matt-taylor-tech/subreddit-sounds/releases/latest"
CHECK_INTERVAL_SEC = 24 * 60 * 60


def is_enabled() -> bool:
    return settings_service.get("update_check_enabled", "true") == "true"


def parse_version(value: str) -> tuple[int, ...] | None:
    """``"v1.2.3"`` -> ``(1, 2, 3)``. None for anything that isn't plain x.y.z."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (value or "").strip())
    return tuple(int(part) for part in match.groups()) if match else None


def is_newer(latest: str, current: str) -> bool:
    latest_v, current_v = parse_version(latest), parse_version(current)
    return bool(latest_v and current_v and latest_v > current_v)


def check_now() -> None:
    """Fetch the latest release and cache it. Never raises."""
    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(
                RELEASES_URL,
                headers={"Accept": "application/vnd.github+json", "User-Agent": f"subreddit-sounds/{get_version()}"},
            )
        if r.status_code != 200:
            return
        data = r.json()
        tag = str(data.get("tag_name", ""))
        if not parse_version(tag):
            return
        settings_service.put_many(
            {
                "update_latest_version": tag.lstrip("v"),
                "update_latest_url": str(data.get("html_url", "")),
                "update_last_check": str(time.time()),
            }
        )
    except Exception:
        pass


def maybe_check() -> None:
    """Scheduler entry point: check if enabled, set up, and the cache is stale."""
    if not is_enabled() or not settings_service.is_setup_complete():
        return
    try:
        last = float(settings_service.get("update_last_check", "0") or 0)
    except ValueError:
        last = 0.0
    if time.time() - last >= CHECK_INTERVAL_SEC:
        check_now()


def available_update() -> dict | None:
    """The cached newer release, or None when up to date / disabled / unknown."""
    if not is_enabled():
        return None
    latest = settings_service.get("update_latest_version", "")
    if not is_newer(latest, get_version()):
        return None
    return {
        "version": latest,
        "url": settings_service.get("update_latest_url", "")
        or "https://github.com/matt-taylor-tech/subreddit-sounds/releases",
        "dismissed": settings_service.get("update_dismissed_version", "") == latest,
    }


def update_context(request: Request) -> dict:
    """Jinja context processor: expose ``update_available`` to signed-in pages."""
    if not request.session.get("is_authenticated"):
        return {"update_available": None}
    return {"update_available": available_update()}
