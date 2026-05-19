from app.services.spotify_service import _select_best_track


def test_select_best_track_prefers_artist_and_title_overlap():
    items = [
        {
            "id": "wrong",
            "name": "Dark Horizon",
            "duration_ms": 240000,
            "popularity": 90,
            "artists": [{"id": "a1", "name": "Random Artist"}],
        },
        {
            "id": "right",
            "name": "Dark Horizon",
            "duration_ms": 240000,
            "popularity": 40,
            "artists": [{"id": "a2", "name": "Intended Artist"}],
        },
    ]
    out = _select_best_track(items, query="Dark Horizon", artist="Intended Artist")
    assert out == "right"


def test_select_best_track_applies_genre_filter_when_artist_genres_known():
    items = [
        {
            "id": "pop-track",
            "name": "Ashes",
            "duration_ms": 250000,
            "popularity": 70,
            "artists": [{"id": "a1", "name": "Same Name"}],
        },
        {
            "id": "metal-track",
            "name": "Ashes",
            "duration_ms": 245000,
            "popularity": 50,
            "artists": [{"id": "a2", "name": "Same Name"}],
        },
    ]
    genres = {"a1": ["dance pop"], "a2": ["melodic death metal"]}
    out = _select_best_track(
        items,
        query="Ashes",
        artist="Same Name",
        genre_filter="metal",
        artist_genres_by_id=genres,
    )
    assert out == "metal-track"


def test_select_best_track_respects_min_duration():
    items = [
        {
            "id": "short",
            "name": "The Signal",
            "duration_ms": 90000,
            "popularity": 10,
            "artists": [{"id": "a1", "name": "Band"}],
        }
    ]
    out = _select_best_track(items, query="The Signal", artist="Band", min_duration_ms=120000)
    assert out is None
