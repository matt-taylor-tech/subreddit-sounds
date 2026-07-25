from __future__ import annotations

from typing import NamedTuple

import httpx

from app import bandcamp_taxonomy

_DISCOVER_URL = "https://bandcamp.com/api/discover/1/discover_web"
# Bandcamp's own search-box autocomplete. Its ``tag`` block is the only public
# way to confirm a tag exists and to get its canonical ``norm_name``. The tag
# *page* (bandcamp.com/tag/<x>) returns HTTP 200 for absolutely anything, and an
# empty discover result can also just mean a real tag with no recent releases.
_AUTOCOMPLETE_URL = "https://bandcamp.com/api/bcsearch_public_api/1/autocomplete_elastic"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Origin": "https://bandcamp.com",
    "Referer": "https://bandcamp.com/discover/",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/json",
}


class TagCheck(NamedTuple):
    """Result of checking one Bandcamp tag.

    ``slug`` carries Bandcamp's canonical ``norm_name`` when the tag resolved,
    so a user's "Post Rock" is stored as the "post-rock" the discover API wants.
    ``definitive`` marks a result we trust enough to block a save on: an empty
    match list proves the tag doesn't exist, but a network failure proves
    nothing. Mirrors ``reddit_service.SubredditCheck``.
    """

    ok: bool
    reason: str
    message: str
    slug: str = ""
    definitive: bool = True


def parse_tags(raw: str) -> list[str]:
    """Split a comma-separated tag field into trimmed, de-duplicated slugs."""
    out: list[str] = []
    seen: set[str] = set()
    for part in (raw or "").split(","):
        tag = part.strip()
        key = tag.lower()
        if tag and key not in seen:
            seen.add(key)
            out.append(tag)
    return out


def _fetch_tag_matches(slug: str) -> list[dict]:
    """Ask Bandcamp's autocomplete for tags matching ``slug``.

    Raises ``httpx.HTTPError`` on transport/status failures and ``ValueError`` on
    an unreadable body; the only network call in the tag-checking path, so tests
    stub this rather than reaching for the shared httpx module.
    """
    with httpx.Client(timeout=15) as client:
        r = client.post(
            _AUTOCOMPLETE_URL,
            headers=_HEADERS,
            json={"search_text": slug, "search_filter": "", "full_page": False, "fan_id": None},
        )
        r.raise_for_status()
    return (r.json().get("tag") or {}).get("matches") or []


def check_tag(tag: str) -> TagCheck:
    """Confirm one tag exists on Bandcamp, resolving it to its canonical slug.

    Tags in the vendored discover taxonomy short-circuit without a request:
    those are the picker's own options, already known-good. Anything else (a
    typed or legacy value) is looked up against Bandcamp's tag index, which also
    covers the many real tags that aren't part of the discover taxonomy.
    """
    slug = (tag or "").strip()
    if not slug:
        return TagCheck(False, "empty", "No Bandcamp tag was provided.")
    if bandcamp_taxonomy.is_known(slug):
        return TagCheck(True, "ok", f"'{slug}' is a Bandcamp discover genre.", slug=slug.lower())

    try:
        matches = _fetch_tag_matches(slug)
    except httpx.HTTPError as exc:
        return TagCheck(False, "error", f"Couldn't reach Bandcamp to check '{slug}': {exc}", definitive=False)
    except ValueError as exc:
        return TagCheck(False, "error", f"Couldn't read Bandcamp's response for '{slug}': {exc}", definitive=False)

    for match in matches:
        norm = (match.get("norm_name") or "").strip()
        if norm:
            return TagCheck(True, "ok", f"'{slug}' matches the Bandcamp tag '{norm}'.", slug=norm)

    return TagCheck(
        False,
        "not_found",
        f"'{slug}' isn't a Bandcamp tag. Pick one from the list, or check the spelling.",
    )


def resolve_tags(tags: list[str], *, skip: set[str] | None = None) -> tuple[list[str], TagCheck | None]:
    """Canonicalize tags, preserving order; return (slugs, first definitive problem).

    Tags whose lowercased form is in ``skip`` pass through unchecked; that's how
    callers grandfather already-saved values so an old target stays editable
    without re-verifying every tag on each save.

    Ambiguous failures (Bandcamp unreachable) keep the tag as typed rather than
    dropping it, matching how an unverifiable subreddit is still allowed through.
    """
    already = skip or set()
    slugs: list[str] = []
    problem: TagCheck | None = None
    for tag in tags:
        stripped = tag.strip()
        if not stripped:
            continue
        if stripped.lower() in already:
            slug = stripped
        else:
            result = check_tag(stripped)
            if result.ok:
                slug = result.slug or stripped
            elif result.definitive:
                if problem is None:
                    problem = result
                continue
            else:
                slug = stripped
        if slug and slug.lower() not in {s.lower() for s in slugs}:
            slugs.append(slug)
    return slugs, problem


def fetch_new_tracks(tag: str, limit: int = 30) -> list[dict]:
    """Fetch recently released albums for a Bandcamp tag via the discover API.

    Returns a list of {"artist": ..., "title": ...} dicts where title is the
    album's featured track (the one Bandcamp highlights), suitable for Spotify search.
    Raises RuntimeError on unexpected API responses.
    """
    payload = {
        "category_id": 0,
        "cursor": "*",
        "geoname_id": 0,
        "include_result_types": ["a", "s"],
        "size": 50,
        "slice": "new",
        "tag_norm_names": [tag],
        "time_facet_id": None,
    }

    with httpx.Client(timeout=15) as client:
        r = client.post(_DISCOVER_URL, headers=_HEADERS, json=payload)
        r.raise_for_status()

    data = r.json()

    if "results" not in data:
        raise RuntimeError(f"Unexpected Bandcamp discover API response (keys: {list(data.keys())})")

    tracks = []
    for item in data["results"]:
        if item.get("result_type") != "a":
            continue
        artist = item.get("band_name", "").strip()
        featured = item.get("featured_track") or {}
        track_title = featured.get("title", "").strip()
        if artist and track_title:
            tracks.append({"artist": artist, "title": track_title})

    return tracks[:limit]
