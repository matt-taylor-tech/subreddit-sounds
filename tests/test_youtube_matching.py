"""Matching accuracy for Reddit's dominant link type: YouTube.

A sample of r/listentothis top/week was ~89% YouTube links, so these cover the
paths that decide whether a post lands on the right Spotify track: how much of a
title survives into the query, and whether a channel-derived artist is treated as
evidence or merely as a hint.
"""

from app.services import spotify_service
from app.services.link_resolver import (
    clean_youtube_title,
    derive_artist_from_channel,
    is_topic_channel,
    parse_youtube_title,
)
from app.services.spotify_service import _fold, _select_best_track


def test_stacked_noise_suffixes_all_stripped():
    # Previously only the last suffix went, leaving "(Official Video)" in the query.
    assert clean_youtube_title("Ashes (Official Video) [4K]") == "Ashes"
    assert clean_youtube_title("Ashes (Official Music Video) (HD) [Remastered]") == "Ashes"


def test_single_and_absent_noise_still_work():
    assert clean_youtube_title("Ashes (Official Video)") == "Ashes"
    assert clean_youtube_title("Ashes") == "Ashes"


def test_parse_title_strips_stacked_noise_too():
    artist, track = parse_youtube_title("Real Band - Ashes (Official Video) [HD]")
    assert artist == "Real Band"
    assert track == "Ashes"


def test_topic_channel_is_trusted_but_curator_channel_is_not():
    assert is_topic_channel("Real Band - Topic")
    assert not is_topic_channel("Majestic Casual")
    assert not is_topic_channel(None)
    # Either way the name is still extracted; only the trust level differs.
    assert derive_artist_from_channel("Real Band - Topic") == "Real Band"
    assert derive_artist_from_channel("Majestic Casual") == "Majestic Casual"


def _items():
    return [
        {
            "id": "right",
            "name": "Ashes",
            "duration_ms": 240000,
            "popularity": 60,
            "artists": [{"id": "a1", "name": "Real Band"}],
        },
        {
            "id": "other",
            "name": "Ashes",
            "duration_ms": 240000,
            "popularity": 20,
            "artists": [{"id": "a2", "name": "Someone Else"}],
        },
    ]


def test_curator_channel_no_longer_rejects_every_candidate():
    # The old behaviour: artist="Majestic Casual" matched no candidate's artist
    # tokens, so the whole post resolved to nothing.
    out = _select_best_track(_items(), query="Ashes", artist="Majestic Casual", artist_is_hint=True)
    assert out == "right"  # falls back to title overlap + popularity


def test_hinted_artist_still_breaks_ties_when_it_agrees():
    out = _select_best_track(_items(), query="Ashes", artist="Someone Else", artist_is_hint=True)
    assert out == "other"  # agreeing hint outweighs the more popular track


def test_known_artist_still_rejects_a_different_artist():
    # Not a hint: a title-parsed artist must still exclude other artists.
    out = _select_best_track(
        [_items()[1]],
        query="Ashes",
        artist="Real Band",
        artist_is_hint=False,
    )
    assert out is None


def test_genre_folding_matches_spotify_spelling():
    assert _fold("math-rock") == "math rock"
    assert _fold("r&b") == "r b"
    assert _fold("Hip-Hop/Rap") == "hip hop rap"


def test_hyphenated_genre_term_no_longer_rejects_classified_artists():
    items = [
        {
            "id": "match",
            "name": "Ashes",
            "duration_ms": 240000,
            "popularity": 50,
            "artists": [{"id": "a1", "name": "Real Band"}],
        }
    ]
    out = _select_best_track(
        items,
        query="Ashes",
        genre_filter="math-rock",  # Spotify spells it "math rock"
        artist_genres_by_id={"a1": ["math rock", "post-rock"]},
    )
    assert out == "match"


def _record_searches(monkeypatch, results):
    """Stub the search+select step, returning results[i] for the i-th call."""
    queries = []

    def _fake(q, *, query, artist, genre_filter, min_duration_ms, artist_is_hint, **kwargs):
        queries.append((q, artist_is_hint))
        return results[len(queries) - 1] if len(queries) <= len(results) else None

    monkeypatch.setattr(spotify_service, "_search_and_select", _fake)
    return queries


def test_hint_tries_precise_search_first(monkeypatch):
    # Self-uploading artist: the field-filtered search hits, so no fallback runs.
    queries = _record_searches(monkeypatch, ["exact-id"])
    out = spotify_service.search_track("Universe for Beginners", artist="Kim Lu", artist_is_hint=True)
    assert out == "exact-id"
    assert len(queries) == 1
    assert queries[0] == ('artist:"Kim Lu" track:"Universe for Beginners"', False)


def test_hint_falls_back_to_freetext_when_precise_finds_nothing(monkeypatch):
    # Curator channel: precise search is empty, so retry freetext with the hint.
    queries = _record_searches(monkeypatch, [None, "fallback-id"])
    out = spotify_service.search_track("Ashes", artist="Majestic Casual", artist_is_hint=True)
    assert out == "fallback-id"
    assert len(queries) == 2
    assert queries[1] == ("Ashes", True)


def test_known_artist_never_falls_back(monkeypatch):
    # A title-parsed artist is trusted; a miss must stay a miss rather than
    # matching some unrelated track with the same title.
    queries = _record_searches(monkeypatch, [None, "should-not-be-used"])
    out = spotify_service.search_track("Ashes", artist="Real Band", artist_is_hint=False)
    assert out is None
    assert len(queries) == 1


def test_genre_filter_uses_one_quoted_term_in_the_query(monkeypatch):
    # "metal, rock" previously produced the malformed q=... genre:metal, rock
    queries = _record_searches(monkeypatch, ["id"])
    spotify_service.search_track("Ashes", genre_filter="metal, rock")
    assert queries[0][0] == 'Ashes genre:"metal"'


def _one(artist_id="a1", name="Ashes", pop=50):
    return [
        {
            "id": "cand",
            "name": name,
            "duration_ms": 240000,
            "popularity": pop,
            "artists": [{"id": artist_id, "name": "Unknown Band"}],
        }
    ]


def test_genre_filtered_target_keeps_a_verified_hint_match():
    # Hinted artist, but Spotify confirms the genre: this is a real gain over the
    # old behaviour, which dropped the post entirely.
    out = _select_best_track(
        _one(),
        query="Ashes",
        artist="Some Channel",
        artist_is_hint=True,
        genre_filter="melodic death metal",
        artist_genres_by_id={"a1": ["melodic death metal"]},
    )
    assert out == "cand"


def test_unclassified_artist_excluded_when_the_target_says_so():
    # One visible setting decides this, on every path, rather than the strictness
    # depending on how the artist happened to be discovered.
    out = _select_best_track(
        _one(),
        query="Ashes",
        artist="Some Channel",
        artist_is_hint=True,
        genre_filter="melodic death metal",
        artist_genres_by_id={"a1": []},
        include_unclassified=False,
    )
    assert out is None


def test_unclassified_artist_included_by_default():
    # Default preserves the historical lenient behaviour, so upgrading an existing
    # target doesn't silently shrink its playlist.
    for hint in (True, False):
        out = _select_best_track(
            _one(),
            query="Ashes",
            artist="Unknown Band",
            artist_is_hint=hint,
            genre_filter="melodic death metal",
            artist_genres_by_id={"a1": []},
        )
        assert out == "cand"


def test_no_genre_filter_leaves_the_hint_path_permissive():
    # Without a genre filter there is nothing to verify against, so a hint match
    # is still allowed through.
    out = _select_best_track(_one(), query="Ashes", artist="Some Channel", artist_is_hint=True)
    assert out == "cand"


def test_genre_filter_still_rejects_a_genuine_mismatch():
    items = [
        {
            "id": "pop",
            "name": "Ashes",
            "duration_ms": 240000,
            "popularity": 90,
            "artists": [{"id": "a1", "name": "Real Band"}],
        }
    ]
    out = _select_best_track(
        items,
        query="Ashes",
        genre_filter="metal",
        artist_genres_by_id={"a1": ["dance pop"]},
    )
    assert out is None
