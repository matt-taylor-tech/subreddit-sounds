import httpx

_DISCOVER_URL = "https://bandcamp.com/api/discover/1/discover_web"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Origin": "https://bandcamp.com",
    "Referer": "https://bandcamp.com/discover/",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/json",
}


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
