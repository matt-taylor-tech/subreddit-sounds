import json
import re

import httpx

_TAG_URL = "https://bandcamp.com/tag/{tag}"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; listige-bot/1.0)"}

# Bandcamp embeds initial hub data as a JS variable in the tag page HTML.
_BLOB_RE = re.compile(r"var\s+blob\s*=\s*(\{.+?\});\s*</script>", re.DOTALL)


def fetch_new_tracks(tag: str, limit: int = 30) -> list[dict]:
    """Fetch recently released tracks for a Bandcamp tag.

    Returns a list of {"artist": ..., "title": ...} dicts (tracks only, not albums).
    Raises RuntimeError with a descriptive message if the page structure is unexpected.
    """
    url = _TAG_URL.format(tag=tag)
    with httpx.Client(follow_redirects=True, timeout=15) as client:
        r = client.get(url, headers=_HEADERS, params={"sort_field": "date"})
        r.raise_for_status()

    match = _BLOB_RE.search(r.text)
    if not match:
        raise RuntimeError(
            f"Could not locate embedded JSON blob on Bandcamp tag page ({url}). "
            "The page structure may have changed."
        )

    data = json.loads(match.group(1))

    try:
        tabs = data["hub"]["tabs"]
    except (KeyError, TypeError) as exc:
        keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
        raise RuntimeError(
            f"Unexpected Bandcamp blob structure (top-level keys: {keys}): {exc}"
        ) from exc

    items: list[dict] = []
    for tab in tabs:
        items.extend(tab.get("items", []))

    tracks = [
        {"artist": item["artist"], "title": item["title"]}
        for item in items
        if item.get("item_type") == "t"
        and item.get("artist")
        and item.get("title")
    ]

    return tracks[:limit]
