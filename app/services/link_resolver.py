from urllib.parse import parse_qs, urlparse


def classify_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "spotify.com" in host or url.startswith("spotify:track:"):
        return "spotify"
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    return "generic"


def extract_spotify_track_id(url: str) -> str | None:
    if url.startswith("spotify:track:"):
        return url.split(":")[-1]

    parsed = urlparse(url)
    if "spotify.com" not in parsed.netloc.lower():
        return None

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and parts[0] == "track":
        return parts[1]

    if parsed.query:
        q = parse_qs(parsed.query)
        if "uri" in q:
            uri = q["uri"][0]
            if uri.startswith("spotify:track:"):
                return uri.split(":")[-1]

    return None
