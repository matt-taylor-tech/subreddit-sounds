#!/usr/bin/env python3
"""Regenerate ``app/bandcamp_taxonomy.py`` from Bandcamp's live discover page.

Bandcamp has no public endpoint that lists its discover genres, but the
``/discover/`` page embeds the whole taxonomy in a ``data-blob`` attribute on
the page shell. We scrape it once here, at development time, and vendor the
result so the app never depends on Bandcamp's HTML shape (or on the network) to
render a form.

Run it when Bandcamp adds genres; the diff is the review:

    python scripts/refresh_bandcamp_taxonomy.py
    ruff format app/bandcamp_taxonomy.py
"""

from __future__ import annotations

import html
import json
import pathlib
import re
import sys

import httpx

_DISCOVER_PAGE = "https://bandcamp.com/discover/"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_OUT_PATH = pathlib.Path(__file__).resolve().parent.parent / "app" / "bandcamp_taxonomy.py"

_HEADER = '''"""Bandcamp's discover genre / subgenre taxonomy.

GENERATED FILE - do not edit by hand. Regenerate with:

    python scripts/refresh_bandcamp_taxonomy.py

Every slug here is a valid ``tag_norm_names`` value for the discover API, so
what the user picks in the form is exactly what gets fetched. Subgenre slugs
are *not* globally unique (``folk`` is both a top-level genre and a subgenre of
``acoustic``), which is why lookups go through the helpers below rather than
assuming a flat unique key.
"""
'''


def fetch_taxonomy() -> tuple[list[dict], list[dict]]:
    """Return (genres, subgenres) as scraped from the discover page blob."""
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        r = client.get(_DISCOVER_PAGE, headers={"User-Agent": _USER_AGENT})
        r.raise_for_status()

    match = re.search(r'data-blob="(.*?)"', r.text, re.S)
    if not match:
        raise SystemExit("Could not find the data-blob attribute; Bandcamp's discover page markup changed.")

    blob = json.loads(html.unescape(match.group(1)))
    try:
        state = blob["appData"]["initialState"]
        genres = state["genres"]
        subgenres = state["subgenres"]
    except KeyError as exc:
        raise SystemExit(f"Discover blob is missing {exc}; the page's data shape changed.") from exc

    if not genres or not subgenres:
        raise SystemExit(f"Refusing to write an empty taxonomy (genres={len(genres)}, subgenres={len(subgenres)}).")
    return genres, subgenres


def render_module(genres: list[dict], subgenres: list[dict]) -> str:
    """Render the generated module source, preserving Bandcamp's own ordering."""
    lines = [_HEADER, "", "GENRES: list[dict[str, str]] = ["]
    for g in genres:
        lines.append(f'    {{"slug": {g["slug"]!r}, "label": {g["label"]!r}}},')
    lines.append("]")
    lines.append("")
    lines.append("SUBGENRES: list[dict[str, str]] = [")
    for s in subgenres:
        lines.append(f'    {{"slug": {s["slug"]!r}, "label": {s["label"]!r}, "parent": {s["parentSlug"]!r}}},')
    lines.append("]")
    lines.append(_HELPERS)
    return "\n".join(lines)


_HELPERS = '''

# Flat set of every slug the discover API will accept, for O(1) validation.
KNOWN_SLUGS: frozenset[str] = frozenset([g["slug"] for g in GENRES] + [s["slug"] for s in SUBGENRES])


def is_known(slug: str) -> bool:
    """True if ``slug`` is part of Bandcamp's discover taxonomy."""
    return slug.strip().lower() in KNOWN_SLUGS


def subgenres_for(genre_slug: str) -> list[dict[str, str]]:
    """Subgenres nested under a top-level genre, in Bandcamp's own order."""
    return [s for s in SUBGENRES if s["parent"] == genre_slug]


def as_picker_payload() -> dict:
    """Taxonomy shaped for the browser picker: genres, each with its subgenres."""
    return {
        "genres": [
            {"slug": g["slug"], "label": g["label"], "subgenres": subgenres_for(g["slug"])} for g in GENRES
        ]
    }
'''


def main() -> int:
    genres, subgenres = fetch_taxonomy()
    _OUT_PATH.write_text(render_module(genres, subgenres))
    print(f"Wrote {_OUT_PATH.relative_to(pathlib.Path.cwd())}: {len(genres)} genres, {len(subgenres)} subgenres.")
    print("Now run: ruff format app/bandcamp_taxonomy.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
