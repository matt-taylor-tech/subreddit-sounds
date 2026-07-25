"""Reddit access: public RSS feed by default, OAuth when credentials exist.

As of Reddit's Responsible Builder Policy (Nov 2025), anonymous access to the
JSON API (``www.reddit.com/*.json``) is blocked with ``403 Blocked`` from most
IPs, and new OAuth credentials require manual approval — self-service app
creation at reddit.com/prefs/apps is gone. The public RSS/Atom feeds
(``/r/<sub>/<sort>.rss``) remain accessible without credentials and carry enough
data (title + external link) for link resolution, so they are the default path.

When a Reddit client ID and secret *are* configured (a grandfathered app, or one
approved via Reddit's developer support process), we use application-only OAuth
(the ``client_credentials`` grant) against ``oauth.reddit.com`` instead, which
returns the richer JSON listing.

Either way, ``fetch_posts`` yields the same shape the resolver expects:
``[{"data": {"url": <external link>, "title": <post title>}}, ...]``.
"""

from __future__ import annotations

import random
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable

import httpx

from app.services import settings_service

_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_OAUTH_API = "https://oauth.reddit.com"
_PUBLIC_API = "https://www.reddit.com"

_ATOM = "{http://www.w3.org/2005/Atom}"
# The external submission URL is the "[link]" anchor inside each entry's HTML
# content (the entry's own <link> always points to the comments page).
_LINK_ANCHOR = re.compile(r'<a\s+href="([^"]+)"\s*>\s*\[link\]', re.IGNORECASE)

# Reddit's public RSS feed is rate-limited; a transient 429 shouldn't abort the
# whole sync. Retry a couple of times with exponential backoff (honouring a
# Retry-After header when present) before giving up.
_MAX_ATTEMPTS = 3
_BACKOFF_BASE = 2.0  # seconds
_MAX_BACKOFF = 30.0  # cap any single wait


def _noop_log(_msg: str) -> None:
    pass


def has_credentials() -> bool:
    """True when both a Reddit client ID and secret are configured."""
    return bool(
        settings_service.get("reddit_client_id")
        and settings_service.get("reddit_client_secret")
    )


def fetch_posts(
    subreddit: str,
    user_agent: str,
    sort: str = "top",
    timeframe: str = "week",
    limit: int = 100,
    log: Callable[[str], None] | None = None,
) -> list[dict]:
    """Fetch a subreddit listing, using OAuth JSON when credentials exist, else RSS.

    ``log`` receives a message for each rate-limit retry so it surfaces in the
    run log; it defaults to a no-op for callers that don't need it.
    """
    log = log or _noop_log
    if has_credentials():
        return _fetch_via_oauth(subreddit, user_agent, sort, timeframe, limit, log)
    return _fetch_via_rss(subreddit, user_agent, sort, timeframe, limit, log)


# ---------------------------------------------------------------------------
# Shared HTTP GET with rate-limit retry
# ---------------------------------------------------------------------------

def _retry_delay(response: httpx.Response, attempt: int) -> float:
    """Seconds to wait before the next attempt: Retry-After if given, else backoff."""
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return min(float(retry_after), _MAX_BACKOFF)
        except ValueError:
            pass
    backoff = min(_BACKOFF_BASE * (2 ** (attempt - 1)), _MAX_BACKOFF)
    return backoff + random.uniform(0, 1)  # jitter to avoid thundering herd


def _get_with_retry(
    client: httpx.Client,
    url: str,
    *,
    headers: dict,
    params: dict,
    subreddit: str,
    user_agent: str,
    log: Callable[[str], None],
) -> httpx.Response:
    """GET ``url``, retrying on 429 with backoff. 403 (hard block) fails at once."""
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        r = client.get(url, headers=headers, params=params)
        if r.status_code == 429:
            if attempt < _MAX_ATTEMPTS:
                delay = _retry_delay(r, attempt)
                log(
                    f"Reddit rate-limited r/{subreddit} (429) — retrying in "
                    f"{delay:.0f}s (retry {attempt}/{_MAX_ATTEMPTS - 1})"
                )
                time.sleep(delay)
                continue
            raise RuntimeError(_blocked_message(429, subreddit, user_agent))
        if r.status_code == 403:
            raise RuntimeError(_blocked_message(403, subreddit, user_agent))
        r.raise_for_status()
        return r
    raise RuntimeError(_blocked_message(429, subreddit, user_agent))  # exhausted


# ---------------------------------------------------------------------------
# Public RSS feed (no credentials required)
# ---------------------------------------------------------------------------

def _fetch_via_rss(
    subreddit: str, user_agent: str, sort: str, timeframe: str, limit: int,
    log: Callable[[str], None],
) -> list[dict]:
    params: dict = {"limit": limit}
    if sort == "top":
        params["t"] = timeframe
    url = f"{_PUBLIC_API}/r/{subreddit}/{sort}.rss"
    with httpx.Client(follow_redirects=True, timeout=15) as client:
        r = _get_with_retry(
            client, url, headers={"User-Agent": user_agent}, params=params,
            subreddit=subreddit, user_agent=user_agent, log=log,
        )
        body = r.text
    return _parse_atom(body)


def _parse_atom(body: str) -> list[dict]:
    """Convert a Reddit Atom feed into the resolver's post shape."""
    root = ET.fromstring(body)
    posts: list[dict] = []
    for entry in root.findall(f"{_ATOM}entry"):
        title_el = entry.find(f"{_ATOM}title")
        title = title_el.text if title_el is not None and title_el.text else "(no title)"

        content_el = entry.find(f"{_ATOM}content")
        content = content_el.text or "" if content_el is not None else ""
        match = _LINK_ANCHOR.search(content)
        if match:
            url = match.group(1)
        else:
            # Self/text post: fall back to the comments permalink, which the
            # resolver classifies as non-music and skips (matching JSON behaviour).
            link_el = entry.find(f"{_ATOM}link")
            url = link_el.get("href", "") if link_el is not None else ""

        posts.append({"data": {"url": url, "title": title}})
    return posts


# ---------------------------------------------------------------------------
# Application-only OAuth (used only when credentials are configured)
# ---------------------------------------------------------------------------

def _fetch_via_oauth(
    subreddit: str, user_agent: str, sort: str, timeframe: str, limit: int,
    log: Callable[[str], None],
) -> list[dict]:
    params: dict = {"limit": limit}
    if sort == "top":
        params["t"] = timeframe
    headers = {
        "User-Agent": user_agent,
        "Authorization": f"Bearer {_get_access_token(user_agent)}",
    }
    url = f"{_OAUTH_API}/r/{subreddit}/{sort}.json"
    with httpx.Client(follow_redirects=True, timeout=15) as client:
        r = _get_with_retry(
            client, url, headers=headers, params=params,
            subreddit=subreddit, user_agent=user_agent, log=log,
        )
    return r.json()["data"]["children"]


def _get_access_token(user_agent: str) -> str:
    """Return a cached app-only bearer token, refreshing it when near expiry."""
    expiry = float(settings_service.get("reddit_token_expiry", "0"))
    if time.time() < expiry - 60:
        cached = settings_service.get("reddit_access_token")
        if cached:
            return cached

    client_id = settings_service.get("reddit_client_id")
    client_secret = settings_service.get("reddit_client_secret")
    with httpx.Client(timeout=15) as client:
        r = client.post(
            _TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
            headers={"User-Agent": user_agent},
        )
        if r.status_code in (401, 403):
            raise RuntimeError(
                f"Reddit OAuth token request failed ({r.status_code}). Verify the Reddit "
                f"client ID & secret in Settings. Note: since Nov 2025 new credentials require "
                f"approval via Reddit's developer support process — self-service app creation "
                f"is no longer available."
            )
        r.raise_for_status()
    data = r.json()
    settings_service.put_many({
        "reddit_access_token": data["access_token"],
        "reddit_token_expiry": str(time.time() + data.get("expires_in", 3600)),
    })
    return data["access_token"]


def _blocked_message(status_code: int, subreddit: str, user_agent: str) -> str:
    if status_code == 429:
        return (
            f"Reddit rate-limited the request for r/{subreddit} (429). The public RSS feed "
            f"allows only a low request rate — wait a minute and retry. A once-daily sync "
            f"stays well within the limit."
        )
    if has_credentials():
        return (
            f"Reddit returned {status_code} for r/{subreddit} even with OAuth credentials. "
            f"The token may be invalid or the subreddit may be private/quarantined. "
            f"Re-check the Reddit client ID & secret in Settings."
        )
    return (
        f"Reddit returned {status_code} for r/{subreddit} on the public RSS feed. This IP "
        f"may be blocked by Reddit. Options: run from a residential IP, or add approved OAuth "
        f"credentials in Settings. Current User-Agent: {user_agent!r}."
    )
