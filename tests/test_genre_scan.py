"""Genre discovery: tally what a target's subreddits actually contain.

Reddit and Spotify are stubbed, so these cover the tallying, the checklist rows
(including genres the user picked that a later scan no longer sees), and the two
explicit matching switches that replaced the old guess-a-string filter.
"""

import json

import pytest

from app.models import Target
from app.services import genre_scan_service, spotify_service


def _target(**kw):
    fields = {
        "name": "Metal",
        "subreddits": "doommetal",
        "genre_filter": None,
        "genre_scan": "",
    }
    fields.update(kw)
    return Target(**fields)


def _stub_scan(monkeypatch, *, resolved, artist_info):
    monkeypatch.setattr(genre_scan_service.spotify_service, "is_connected", lambda: True)
    # No DB in these tests; the scan only reads the shared read options.
    monkeypatch.setattr(genre_scan_service.settings_service, "get", lambda key, default="": default or "stub")
    monkeypatch.setattr(
        genre_scan_service.reddit_service,
        "fetch_posts",
        lambda sub, ua, sort="top", timeframe="week", limit=50, log=None: [{"data": {"url": "u", "title": "t"}}] * 3,
    )
    monkeypatch.setattr(genre_scan_service.sync_service, "min_duration_ms", lambda: None)
    monkeypatch.setattr(
        genre_scan_service.sync_service,
        "collect_tracks",
        lambda posts, log, genre_filter=None, min_duration_ms=None: (resolved, 0),
    )
    monkeypatch.setattr(genre_scan_service.spotify_service, "get_primary_artist_genres", lambda ids: artist_info)


def test_scan_tallies_genres_most_common_first(monkeypatch):
    _stub_scan(
        monkeypatch,
        resolved=["t1", "t2", "t3"],
        artist_info={
            "t1": ("Band A", ["death metal", "melodic death metal"]),
            "t2": ("Band B", ["death metal"]),
            "t3": ("Band C", ["doom metal"]),
        },
    )
    result = genre_scan_service.scan_target(_target())
    assert [g["name"] for g in result["genres"]] == ["death metal", "doom metal", "melodic death metal"]
    assert result["genres"][0]["count"] == 2
    assert result["resolved"] == 3
    assert result["unclassified"] == 0
    assert result["subreddits"] == ["doommetal"]


def test_scan_counts_unclassified_artists_separately(monkeypatch):
    _stub_scan(
        monkeypatch,
        resolved=["t1", "t2"],
        artist_info={"t1": ("Band A", ["death metal"]), "t2": ("Small Band", [])},
    )
    result = genre_scan_service.scan_target(_target())
    assert result["unclassified"] == 1
    assert [g["name"] for g in result["genres"]] == ["death metal"]


def test_scan_requires_a_subreddit(monkeypatch):
    monkeypatch.setattr(genre_scan_service.spotify_service, "is_connected", lambda: True)
    with pytest.raises(ValueError, match="at least one subreddit"):
        genre_scan_service.scan_target(_target(subreddits=""))


def test_scan_requires_spotify(monkeypatch):
    monkeypatch.setattr(genre_scan_service.spotify_service, "is_connected", lambda: False)
    with pytest.raises(RuntimeError, match="Connect Spotify"):
        genre_scan_service.scan_target(_target())


def test_scan_survives_one_failing_subreddit(monkeypatch):
    _stub_scan(monkeypatch, resolved=["t1"], artist_info={"t1": ("Band", ["death metal"])})
    calls = []

    def _fetch(sub, ua, sort="top", timeframe="week", limit=50, log=None):
        calls.append(sub)
        if sub == "broken":
            raise RuntimeError("429")
        return [{"data": {"url": "u", "title": "t"}}]

    monkeypatch.setattr(genre_scan_service.reddit_service, "fetch_posts", _fetch)
    result = genre_scan_service.scan_target(_target(subreddits="broken, doommetal"))
    assert calls == ["broken", "doommetal"]
    assert result["genres"]  # the good subreddit still counted


def _scan_json(genres, unclassified=0):
    return json.dumps(
        {
            "genres": [{"name": n, "count": c} for n, c in genres],
            "unclassified": unclassified,
            "resolved": 10,
            "posts": 20,
            "subreddits": ["doommetal"],
            "scanned_at": "2026-07-25T16:00:00",
        }
    )


def test_picker_rows_mark_current_selection():
    target = _target(
        genre_scan=_scan_json([("death metal", 5), ("doom metal", 2)]),
        genre_filter="death metal",
    )
    rows = genre_scan_service.picker_rows(target)
    assert [(r["name"], r["checked"]) for r in rows] == [("death metal", True), ("doom metal", False)]


def test_picker_rows_keep_a_pick_that_dropped_out_of_the_scan():
    # Otherwise saving the form would silently discard a genre the user chose.
    target = _target(
        genre_scan=_scan_json([("death metal", 5)]),
        genre_filter="death metal, melodic death metal",
    )
    rows = genre_scan_service.picker_rows(target)
    assert [(r["name"], r["checked"], r["count"]) for r in rows] == [
        ("death metal", True, 5),
        ("melodic death metal", True, None),
    ]


def test_load_scan_tolerates_missing_or_corrupt_data():
    assert genre_scan_service.load_scan(_target()) is None
    assert genre_scan_service.load_scan(_target(genre_scan="not json")) is None
    assert genre_scan_service.load_scan(_target(genre_scan='{"other": 1}')) is None


def test_substyles_switch_controls_family_matching():
    genres = ["melodic death metal"]
    terms = ["death metal"]
    assert spotify_service._genre_matches(genres, terms, include_substyles=True)
    assert not spotify_service._genre_matches(genres, terms, include_substyles=False)
    # Exact ticks always match, whatever the switch says.
    assert spotify_service._genre_matches(genres, ["melodic death metal"], include_substyles=False)


def test_substyle_matching_respects_word_boundaries():
    # "metal" must not drag in "metalcore": it's a separate genre with its own row.
    assert spotify_service._genre_matches(["doom metal"], ["metal"])
    assert not spotify_service._genre_matches(["metalcore"], ["metal"])
