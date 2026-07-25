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
    r"(official\s*(music\s*)?video|official\s*audio|official|lyric(s)?\s*video|"
    r"live(\s+at\s+\w+)?|full\s*album|hd|hq|4k|audio|video|visualizer|"
    r"remaster(ed)?|remix)"
    r"[\)\]]\s*$",
    re.IGNORECASE,
)

# Hyphen, en dash, or em dash, each surrounded by whitespace — YouTube titles
# use all three for the artist/track separator (label uploads often use en dash).
_DASH_SPLIT = re.compile(r"\s+[-–—]\s+")


def _strip_noise(title: str) -> str:
    """Strip every trailing noise suffix, not just the last one.

    Real titles stack them ("Song (Official Video) [4K]"), and each leftover
    marker becomes a junk token in the Spotify search query.
    """
    cleaned = title.strip()
    while True:
        stripped = _NOISE.sub("", cleaned).strip()
        if stripped == cleaned:
            return stripped
        cleaned = stripped


def clean_youtube_title(title: str) -> str:
    """Strip common YouTube noise suffixes to improve Spotify search accuracy."""
    return _strip_noise(title)


def parse_youtube_title(title: str) -> tuple[str | None, str]:
    """Split "Artist - Track Title (noise)" into (artist, track).

    Accepts hyphen, en dash, or em dash as the separator (with surrounding
    whitespace). Returns (None, cleaned_title) when no separator is found,
    signalling the caller to fall back to a channel-derived artist hint.
    """
    cleaned = _strip_noise(title)
    match = _DASH_SPLIT.search(cleaned)
    if match:
        artist = cleaned[: match.start()].strip()
        track = cleaned[match.end() :].strip()
        if artist:
            return artist, track
    return None, cleaned


def is_full_album(title: str) -> bool:
    return bool(re.search(r"\bfull\s+album\b", title, re.IGNORECASE))


_TOPIC_SUFFIX = " - Topic"


def is_topic_channel(channel: str | None) -> bool:
    """True for YouTube's auto-generated "{Artist} - Topic" artist channels.

    Those name the artist reliably. Every other channel name is a guess: labels,
    curators and compilation channels ("Majestic Casual", "NPR Music") all post
    other people's music, so their name must not be used to reject candidates.
    """
    return bool(channel and channel.strip().endswith(_TOPIC_SUFFIX))


def derive_artist_from_channel(channel: str | None) -> str | None:
    """Best-effort artist hint from a YouTube channel name.

    Recognises the "{Artist} - Topic" convention (YouTube's auto-generated
    artist channels) and returns the cleaned name. Falls back to the raw
    channel name so self-uploaded band videos still get an artist signal.
    Callers should treat the result as a hint, not a guarantee, unless
    ``is_topic_channel`` says otherwise.
    """
    if not channel:
        return None
    channel = channel.strip()
    if not channel:
        return None
    if channel.endswith(_TOPIC_SUFFIX):
        return channel[: -len(_TOPIC_SUFFIX)].strip() or None
    return channel
