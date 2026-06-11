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

import re
import time
import xml.etree.ElementTree as ET

import httpx

from app.services import settings_service

_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_OAUTH_API = "https://oauth.reddit.com"
_PUBLIC_API = "https://www.reddit.com"

_ATOM = "{http://www.w3.org/2005/Atom}"
# The external submission URL is the "[link]" anchor inside each entry's HTML
# content (the entry's own <link> always points to the comments page).
_LINK_ANCHOR = re.compile(r'<a\s+href="([^"]+)"\s*>\s*\[link\]', re.IGNORECASE)


def has_credentials() -> bool:
    """True when both a Reddit client ID and secret are configured."""
    return bool(
        settings_service.get("reddit_client_id")
        and settings_service.get("reddit_client_secret")
    )


def fetch_posts(
    subreddit: str, user_agent: str, sort: str = "top", timeframe: str = "week", limit: int = 100
) -> list[dict]:
    """Fetch a subreddit listing, using OAuth JSON when credentials exist, else RSS."""
    if has_credentials():
        return _fetch_via_oauth(subreddit, user_agent, sort, timeframe, limit)
    return _fetch_via_rss(subreddit, user_agent, sort, timeframe, limit)


# ---------------------------------------------------------------------------
# Public RSS feed (no credentials required)
# ---------------------------------------------------------------------------

def _fetch_via_rss(
    subreddit: str, user_agent: str, sort: str, timeframe: str, limit: int
) -> list[dict]:
    params: dict = {"limit": limit}
    if sort == "top":
        params["t"] = timeframe
    url = f"{_PUBLIC_API}/r/{subreddit}/{sort}.rss"
    with httpx.Client(follow_redirects=True, timeout=15) as client:
        r = client.get(url, headers={"User-Agent": user_agent}, params=params)
        if r.status_code in (403, 429):
            raise RuntimeError(_blocked_message(r.status_code, subreddit, user_agent))
        r.raise_for_status()
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
    subreddit: str, user_agent: str, sort: str, timeframe: str, limit: int
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
        r = client.get(url, headers=headers, params=params)
        if r.status_code in (403, 429):
            raise RuntimeError(_blocked_message(r.status_code, subreddit, user_agent))
        r.raise_for_status()
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
