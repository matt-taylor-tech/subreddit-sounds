from app.services.link_resolver import classify_url, extract_spotify_track_id, parse_youtube_title


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
