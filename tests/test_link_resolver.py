from app.services.link_resolver import classify_url, extract_spotify_track_id


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
