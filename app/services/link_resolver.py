import re
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


def extract_youtube_video_id(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if "youtu.be" in host:
        vid = parsed.path.lstrip("/").split("/")[0]
        return vid or None
    if "youtube.com" in host:
        if parsed.query:
            q = parse_qs(parsed.query)
            if "v" in q:
                return q["v"][0]
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] in ("shorts", "embed", "v"):
            return parts[1]
    return None


_NOISE = re.compile(
    r"\s*[\(\[]"
    r"(official\s*(music\s*)?video|official\s*audio|lyric(s)?\s*video|"
    r"live(\s+at\s+\w+)?|full\s*album|hd|hq|4k|audio|video|visualizer|"
    r"remaster(ed)?|remix)"
    r"[\)\]]\s*$",
    re.IGNORECASE,
)


def clean_youtube_title(title: str) -> str:
    """Strip common YouTube noise suffixes to improve Spotify search accuracy."""
    return _NOISE.sub("", title).strip()


def is_full_album(title: str) -> bool:
    return bool(re.search(r"\bfull\s+album\b", title, re.IGNORECASE))
