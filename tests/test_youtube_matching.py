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


def test_curator_channel_without_corroboration_matches_nothing():
    # A curator channel agrees with no candidate and there is no genre filter to
    # confirm one, so the only tie-breaker left is popularity — which is how a
    # lounge-jazz track with the same song name wins over the posted one. Better
    # to resolve nothing than to resolve the wrong track.
    out = _select_best_track(_items(), query="Ashes", artist="Majestic Casual", artist_is_hint=True)
    assert out is None


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


def test_unclassified_artist_included_by_default_on_the_trusted_path():
    # Default preserves the historical lenient behaviour, so upgrading an existing
    # target doesn't silently shrink its playlist.
    out = _select_best_track(
        _one(),
        query="Ashes",
        artist="Unknown Band",
        artist_is_hint=False,
        genre_filter="melodic death metal",
        artist_genres_by_id={"a1": []},
    )
    assert out == "cand"


def test_include_unclassified_does_not_reopen_the_hinted_path():
    # "Include unclassified artists" is about not dropping good tracks over absent
    # metadata on the trusted path. It must not also waive the genre check for a
    # match whose only evidence is a shared song title.
    out = _select_best_track(
        _one(),
        query="Ashes",
        artist="Some Channel",
        artist_is_hint=True,
        genre_filter="melodic death metal",
        artist_genres_by_id={"a1": []},
        include_unclassified=True,
    )
    assert out is None


def test_hinted_match_needs_artist_agreement_or_a_confirmed_genre():
    # With no genre filter there is nothing to verify against, so the hint itself
    # has to agree with the candidate's artist.
    agreeing = _select_best_track(_one(), query="Ashes", artist="Unknown Band", artist_is_hint=True)
    assert agreeing == "cand"
    disagreeing = _select_best_track(_one(), query="Ashes", artist="Some Channel", artist_is_hint=True)
    assert disagreeing is None


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


# ---------------------------------------------------------------------------
# The reported regression: a jazz track on a melodic death metal playlist
# ---------------------------------------------------------------------------


def _time_goes_by_candidates():
    """What Spotify returns for a bare "Time Goes By" freetext search.

    The posted track is by an obscure band Spotify hasn't classified; the popular
    homonym is a lounge-jazz ensemble. Popularity alone picks the wrong one.
    """
    return [
        {
            "id": "jazz",
            "name": "Time Goes By",
            "duration_ms": 300000,
            "popularity": 55,
            "artists": [{"id": "jz", "name": "Midnight Groove Ensemble"}],
        },
        {
            "id": "posted",
            "name": "Time Goes By",
            "duration_ms": 260000,
            "popularity": 8,
            "artists": [{"id": "md", "name": "Aether Requiem"}],
        },
    ]


def test_jazz_homonym_no_longer_lands_on_a_metal_playlist():
    # A label/curator channel gives no artist evidence and Spotify has classified
    # neither artist, so nothing confirms either candidate belongs.
    out = _select_best_track(
        _time_goes_by_candidates(),
        query="Time Goes By",
        artist="Metal Label Records",
        artist_is_hint=True,
        genre_filter="melodic death metal",
        artist_genres_by_id={},
    )
    assert out is None


def test_confirmed_genre_still_picks_the_posted_track_over_the_popular_homonym():
    # Same search, but Spotify classifies both artists: the filter now has real
    # evidence and rejects the jazz track on its genre, not on its popularity.
    out = _select_best_track(
        _time_goes_by_candidates(),
        query="Time Goes By",
        artist="Metal Label Records",
        artist_is_hint=True,
        genre_filter="melodic death metal",
        artist_genres_by_id={
            "jz": ["jazz", "lounge"],
            "md": ["melodic death metal"],
        },
    )
    assert out == "posted"


def test_hinted_path_needs_most_of_the_title_to_match():
    items = [
        {
            "id": "partial",
            "name": "Time",
            "duration_ms": 300000,
            "popularity": 90,
            "artists": [{"id": "a1", "name": "Unrelated"}],
        }
    ]
    # One shared word out of three is not a title match.
    assert _select_best_track(items, query="Time Goes By", artist="A Channel", artist_is_hint=True) is None
    # A trusted artist already narrows the field, so partial titles stay allowed.
    assert _select_best_track(items, query="Time Goes By", artist="Unrelated", artist_is_hint=False) == "partial"
