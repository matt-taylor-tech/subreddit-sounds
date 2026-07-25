"""Multi-subreddit fan-out in the sync pipeline (issue #3).

Exercises the extracted `_fetch_all_posts` helper: it fetches each subreddit,
concatenates posts, and treats one failing subreddit as non-fatal. (Request
pacing now lives process-wide inside reddit_service; see test_reddit_service.)
"""

from app.services import sync_service


def _fake_fetch_factory(bad=frozenset()):
    def fake_fetch(sub, user_agent, sort, timeframe, log=None):
        if sub in bad:
            raise RuntimeError("403 blocked")
        return [{"data": {"url": f"u_{sub}", "title": sub}}]

    return fake_fetch


def test_fetch_all_posts_concatenates(monkeypatch):
    monkeypatch.setattr(sync_service.reddit_service, "fetch_posts", _fake_fetch_factory())
    logs: list = []

    posts = sync_service._fetch_all_posts(["a", "b", "c"], "UA", "top", "week", logs.append)

    assert [p["data"]["url"] for p in posts] == ["u_a", "u_b", "u_c"]
    assert any("r/a" in m for m in logs)


def test_fetch_all_posts_one_bad_sub_is_not_fatal(monkeypatch):
    monkeypatch.setattr(sync_service.reddit_service, "fetch_posts", _fake_fetch_factory(bad={"bad"}))
    logs: list = []

    posts = sync_service._fetch_all_posts(["good", "bad", "good2"], "UA", "top", "week", logs.append)

    assert sorted(p["data"]["url"] for p in posts) == ["u_good", "u_good2"]
    assert any("[r/bad] ERROR" in m for m in logs)
