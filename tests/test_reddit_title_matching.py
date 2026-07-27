"""Using the Reddit post title as an artist source.

Music subreddits enforce "Artist - Song [Subgenre] (Year)" in the post title, so
on r/melodicdeathmetal and its siblings the poster names the artist on nearly
every submission. That was previously thrown away: when a YouTube title carried
no "Artist - Track" separator the resolver skipped straight to the channel name,
which is often a label or curator and gives no real evidence of who the artist
is.
"""

from app.services import sync_service
from app.services.link_resolver import parse_reddit_title, strip_reddit_tags


def test_subreddit_tags_are_stripped():
    assert strip_reddit_tags("Insomnium - While We Sleep [Melodic Death Metal] (2014)") == "Insomnium - While We Sleep"
    assert strip_reddit_tags("Some Band - Ashes [Melodeath]") == "Some Band - Ashes"
    assert strip_reddit_tags("Some Band - Ashes (2011)") == "Some Band - Ashes"


def test_untagged_titles_survive_untouched():
    assert strip_reddit_tags("Some Band - Ashes") == "Some Band - Ashes"
    # A parenthesised group that isn't a year is part of the track name.
    assert strip_reddit_tags("Some Band - Ashes (Reprise)") == "Some Band - Ashes (Reprise)"


def test_noise_suffixes_still_come_off_after_the_tags():
    assert strip_reddit_tags("Some Band - Ashes (Official Video) [Melodeath]") == "Some Band - Ashes"


def test_post_title_splits_into_artist_and_track():
    assert parse_reddit_title("Insomnium - While We Sleep [Melodic Death Metal] (2014)") == (
        "Insomnium",
        "While We Sleep",
    )
    # No separator: nothing to trust, so the caller falls through to the channel.
    assert parse_reddit_title("check out this band [Melodeath]") == (None, "check out this band")


def _run_collect(monkeypatch, *, post_title, yt_title, yt_channel):
    """Resolve one YouTube post, capturing what search_track was asked for."""
    captured = {}

    monkeypatch.setattr(sync_service, "_youtube_meta", lambda vid: (yt_title, yt_channel))

    def _fake_search(query, **kwargs):
        captured["query"] = query
        captured.update(kwargs)
        return "track-id"

    monkeypatch.setattr(sync_service.spotify_service, "search_track", _fake_search)
    posts = [{"data": {"url": "https://www.youtube.com/watch?v=abc123", "title": post_title}}]
    sync_service.collect_tracks(posts, log=lambda _m: None)
    return captured


def test_post_title_supplies_a_trusted_artist_when_the_video_title_has_none(monkeypatch):
    captured = _run_collect(
        monkeypatch,
        post_title="Aether Requiem - Time Goes By [Melodic Death Metal] (2023)",
        yt_title="Time Goes By",
        yt_channel="Metal Label Records",
    )
    assert captured["artist"] == "Aether Requiem"
    assert captured["query"] == "Time Goes By"
    # Trusted, so a different artist can still reject a candidate.
    assert captured["artist_is_hint"] is False


def test_video_title_still_wins_when_it_names_the_artist(monkeypatch):
    captured = _run_collect(
        monkeypatch,
        post_title="Someone Else - Wrong Song [Melodeath]",
        yt_title="Real Band - Ashes (Official Video)",
        yt_channel="Metal Label Records",
    )
    assert captured["artist"] == "Real Band"
    assert captured["query"] == "Ashes"
    assert captured["artist_is_hint"] is False


def test_channel_hint_remains_the_last_resort(monkeypatch):
    captured = _run_collect(
        monkeypatch,
        post_title="this rules",
        yt_title="Time Goes By",
        yt_channel="Metal Label Records",
    )
    assert captured["artist"] == "Metal Label Records"
    assert captured["artist_is_hint"] is True


def test_topic_channel_stays_trusted(monkeypatch):
    captured = _run_collect(
        monkeypatch,
        post_title="this rules",
        yt_title="Time Goes By",
        yt_channel="Aether Requiem - Topic",
    )
    assert captured["artist"] == "Aether Requiem"
    assert captured["artist_is_hint"] is False
