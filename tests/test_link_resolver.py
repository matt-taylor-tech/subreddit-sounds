from app.services.link_resolver import (
    classify_url,
    derive_artist_from_channel,
    extract_spotify_track_id,
    normalize_spotify_playlist_id,
    parse_youtube_title,
)


def test_classify_spotify_url():
    assert classify_url("https://open.spotify.com/track/abc123") == "spotify"


def test_classify_youtube_url():
    assert classify_url("https://youtu.be/xyz") == "youtube"


def test_extract_spotify_track_id_from_url():
    assert extract_spotify_track_id("https://open.spotify.com/track/abc123?si=1") == "abc123"


def test_extract_spotify_track_id_from_uri():
    assert extract_spotify_track_id("spotify:track:abc123") == "abc123"


def test_extract_spotify_track_id_non_spotify():
    assert extract_spotify_track_id("https://youtube.com/watch?v=1") is None


def test_parse_youtube_title_standard():
    artist, track = parse_youtube_title("Dark Tranquillity - Monochromatic Stains (Official Video)")
    assert artist == "Dark Tranquillity"
    assert track == "Monochromatic Stains"


def test_parse_youtube_title_no_separator():
    artist, track = parse_youtube_title("Monochromatic Stains (Official Audio)")
    assert artist is None
    assert track == "Monochromatic Stains"


def test_parse_youtube_title_no_noise():
    artist, track = parse_youtube_title("In Flames - The Quiet Place")
    assert artist == "In Flames"
    assert track == "The Quiet Place"


def test_parse_youtube_title_nested_dash_in_track():
    # Only the first " - " splits artist; rest stays in track title
    artist, track = parse_youtube_title("Be'lakor - Vessels - Lilt (Official)")
    assert artist == "Be'lakor"
    assert track == "Vessels - Lilt"


def test_parse_youtube_title_en_dash():
    artist, track = parse_youtube_title("DARK TRANQUILLITY – Unforgivable (OFFICIAL VIDEO)")
    assert artist == "DARK TRANQUILLITY"
    assert track == "Unforgivable"


def test_parse_youtube_title_em_dash():
    artist, track = parse_youtube_title("Insomnium — Mortal Share")
    assert artist == "Insomnium"
    assert track == "Mortal Share"


def test_derive_artist_from_channel_strips_topic_suffix():
    assert derive_artist_from_channel("Insomnium - Topic") == "Insomnium"


def test_derive_artist_from_channel_returns_raw_channel_otherwise():
    assert derive_artist_from_channel("Be'lakor Official") == "Be'lakor Official"


def test_derive_artist_from_channel_handles_empty():
    assert derive_artist_from_channel(None) is None
    assert derive_artist_from_channel("") is None
    assert derive_artist_from_channel("   ") is None


def test_normalize_playlist_id_accepts_share_links_and_uris():
    pid = "1UXnaj6qDYSoQW4745cndy"
    assert normalize_spotify_playlist_id(pid) == pid
    assert normalize_spotify_playlist_id(f"  {pid} ") == pid
    assert normalize_spotify_playlist_id(f"spotify:playlist:{pid}") == pid
    assert normalize_spotify_playlist_id(f"https://open.spotify.com/playlist/{pid}?si=abc123") == pid
    assert normalize_spotify_playlist_id(f"https://open.spotify.com/intl-de/playlist/{pid}") == pid


def test_normalize_playlist_id_leaves_unrecognised_input_alone():
    # Anything else is stored as typed, so Spotify's own error names the bad value.
    assert normalize_spotify_playlist_id("https://example.com/x") == "https://example.com/x"
    assert normalize_spotify_playlist_id("") == ""
