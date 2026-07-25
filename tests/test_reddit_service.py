"""Tests for Reddit access: public RSS by default, OAuth JSON when configured."""

import httpx
import pytest

from app.services import reddit_service

UA = "web:subreddit-sounds:0.1 (by /u/suiifelse)"

# Minimal Reddit Atom feed: one external-link post and one self/text post.
ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Some Band - Great Song</title>
    <link href="https://www.reddit.com/r/x/comments/aaa/great_song/" />
    <content type="html">&lt;a href="https://youtu.be/abc123"&gt; [link] &lt;/a&gt;
      &lt;a href="https://www.reddit.com/r/x/comments/aaa/great_song/"&gt; [comments] &lt;/a&gt;</content>
  </entry>
  <entry>
    <title>Discussion: favourite albums?</title>
    <link href="https://www.reddit.com/r/x/comments/bbb/discussion/" />
    <content type="html">&lt;p&gt;Just text, no external link.&lt;/p&gt;</content>
  </entry>
</feed>"""


class FakeResp:
    def __init__(self, status, *, text="", payload=None, headers=None):
        self.status_code = status
        self.text = text
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"unexpected raise_for_status on {self.status_code}")


class FakeClient:
    """Records every request; returns RSS text for GETs, a token for POSTs.

    ``get_statuses`` (a list) returns a different status per GET, repeating the
    last one once exhausted — used to simulate a 429 that later recovers.
    """

    def __init__(self, calls, *, get_status=200, get_statuses=None, get_text=ATOM, get_json=None, **kwargs):
        self._calls = calls
        self._get_status = get_status
        self._get_statuses = list(get_statuses) if get_statuses else None
        self._get_text = get_text
        self._get_json = get_json or {"data": {"children": [{"data": {"url": "u", "title": "t"}}]}}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, data=None, auth=None, headers=None):
        self._calls.append(("POST", url, auth, (headers or {}).get("User-Agent")))
        return FakeResp(200, payload={"access_token": "TOK123", "expires_in": 3600})

    def get(self, url, headers=None, params=None):
        self._calls.append(("GET", url, (headers or {}).get("Authorization"), params))
        if self._get_statuses:
            status = self._get_statuses.pop(0) if len(self._get_statuses) > 1 else self._get_statuses[0]
        else:
            status = self._get_status
        return FakeResp(status, text=self._get_text, payload=self._get_json)


@pytest.fixture
def settings(monkeypatch):
    store: dict[str, str] = {}
    monkeypatch.setattr(reddit_service.settings_service, "get", lambda k, d="": store.get(k, d))
    monkeypatch.setattr(reddit_service.settings_service, "put_many", lambda p: store.update(p))
    return store


def _patch_httpx(monkeypatch, calls, **resp):
    monkeypatch.setattr(reddit_service.httpx, "Client", lambda **kw: FakeClient(calls, **resp, **kw))


def test_rss_feed_used_when_no_credentials(settings, monkeypatch):
    calls: list = []
    _patch_httpx(monkeypatch, calls)

    posts = reddit_service.fetch_posts("MelodicDeathMetal", UA, "top", "month", 100)

    assert reddit_service.has_credentials() is False
    get = next(c for c in calls if c[0] == "GET")
    assert get[1] == "https://www.reddit.com/r/MelodicDeathMetal/top.rss"
    assert get[2] is None  # no Authorization header
    assert get[3] == {"limit": 100, "t": "month"}
    assert not any(c[0] == "POST" for c in calls)  # never asks for a token

    # link post -> external URL from the [link] anchor; self post -> comments permalink
    assert posts[0] == {"data": {"url": "https://youtu.be/abc123", "title": "Some Band - Great Song"}}
    assert posts[1]["data"]["url"] == "https://www.reddit.com/r/x/comments/bbb/discussion/"
    assert posts[1]["data"]["title"] == "Discussion: favourite albums?"


def test_non_top_sort_omits_timeframe(settings, monkeypatch):
    calls: list = []
    _patch_httpx(monkeypatch, calls)

    reddit_service.fetch_posts("X", UA, "hot")

    get = next(c for c in calls if c[0] == "GET")
    assert get[1].endswith("/hot.rss")
    assert "t" not in get[3]


def test_oauth_json_used_when_credentials_present(settings, monkeypatch):
    settings["reddit_client_id"] = "cid"
    settings["reddit_client_secret"] = "secret"
    calls: list = []
    _patch_httpx(monkeypatch, calls)

    posts = reddit_service.fetch_posts("MelodicDeathMetal", UA, "top", "month", 100)

    assert reddit_service.has_credentials() is True
    post = next(c for c in calls if c[0] == "POST")
    assert post[1] == "https://www.reddit.com/api/v1/access_token"
    assert post[2] == ("cid", "secret")  # HTTP Basic auth
    assert post[3] == UA
    get = next(c for c in calls if c[0] == "GET")
    assert get[1] == "https://oauth.reddit.com/r/MelodicDeathMetal/top.json"
    assert get[2] == "Bearer TOK123"
    assert posts == [{"data": {"url": "u", "title": "t"}}]
    assert settings["reddit_access_token"] == "TOK123"


def test_oauth_token_is_cached(settings, monkeypatch):
    settings["reddit_client_id"] = "cid"
    settings["reddit_client_secret"] = "secret"
    calls: list = []
    _patch_httpx(monkeypatch, calls)

    reddit_service.fetch_posts("A", UA, "top", "week")
    calls.clear()
    reddit_service.fetch_posts("B", UA, "new")

    assert not any(c[0] == "POST" for c in calls)  # token reused, no re-auth


def test_rss_403_raises_actionable_error(settings, monkeypatch):
    calls: list = []
    _patch_httpx(monkeypatch, calls, get_status=403)

    with pytest.raises(RuntimeError) as exc:
        reddit_service.fetch_posts("MelodicDeathMetal", UA, "top", "month")

    msg = str(exc.value)
    assert "403" in msg
    assert "RSS" in msg


def test_429_persistent_retries_then_raises(settings, monkeypatch):
    slept: list = []
    monkeypatch.setattr(reddit_service.time, "sleep", lambda s: slept.append(s))
    calls: list = []
    _patch_httpx(monkeypatch, calls, get_status=429)

    with pytest.raises(RuntimeError) as exc:
        reddit_service.fetch_posts("X", UA, "top", "week")

    assert "429" in str(exc.value)
    assert "rate" in str(exc.value).lower()
    # retried up to the cap before giving up: 3 GETs, 2 backoff sleeps
    assert sum(1 for c in calls if c[0] == "GET") == 3
    assert len(slept) == 2


def test_429_retries_then_succeeds(settings, monkeypatch):
    slept: list = []
    monkeypatch.setattr(reddit_service.time, "sleep", lambda s: slept.append(s))
    calls: list = []
    _patch_httpx(monkeypatch, calls, get_statuses=[429, 200])
    logs: list = []

    posts = reddit_service.fetch_posts("X", UA, "top", "week", log=logs.append)

    assert len(slept) == 1  # one backoff, then success
    assert sum(1 for c in calls if c[0] == "GET") == 2
    assert any("429" in m and "retry" in m.lower() for m in logs)
    assert posts[0]["data"]["url"] == "https://youtu.be/abc123"


def test_403_not_retried(settings, monkeypatch):
    slept: list = []
    monkeypatch.setattr(reddit_service.time, "sleep", lambda s: slept.append(s))
    calls: list = []
    _patch_httpx(monkeypatch, calls, get_status=403)

    with pytest.raises(RuntimeError):
        reddit_service.fetch_posts("X", UA, "top", "week")

    # a hard block fails immediately: one GET, no backoff
    assert sum(1 for c in calls if c[0] == "GET") == 1
    assert slept == []


# --- normalize_subreddit -----------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("MelodicDeathMetal", "MelodicDeathMetal"),
        ("  spaced  ", "spaced"),
        ("r/Foo", "Foo"),
        ("/r/Foo", "Foo"),
        ("R/Foo/", "Foo"),
        ("", ""),
    ],
)
def test_normalize_subreddit(raw, expected):
    assert reddit_service.normalize_subreddit(raw) == expected


# --- parse_subreddits --------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Metal", ["Metal"]),  # single value, backward compatible
        ("a, b ,c", ["a", "b", "c"]),
        ("r/a, /r/B", ["a", "B"]),  # prefixes stripped per item
        ("a, A, a", ["a"]),  # case-insensitive dedup, order preserved
        ("sub1+sub2", ["sub1+sub2"]),  # Reddit multi kept intact as one entry
        ("", []),
        ("  ,  , ", []),
    ],
)
def test_parse_subreddits(raw, expected):
    assert reddit_service.parse_subreddits(raw) == expected


# --- request pacing (issue #33) ----------------------------------------------


def test_request_delay_default_without_credentials(settings):
    assert reddit_service.request_delay_seconds() == 2.0


def test_request_delay_capped_with_credentials(settings):
    settings["reddit_client_id"] = "cid"
    settings["reddit_client_secret"] = "secret"
    settings["reddit_request_delay_sec"] = "5"
    # OAuth has higher limits, so the delay is capped low.
    assert reddit_service.request_delay_seconds() == 1.0


def test_request_delay_invalid_falls_back(settings):
    settings["reddit_request_delay_sec"] = "not-a-number"
    assert reddit_service.request_delay_seconds() == 2.0


def test_pace_next_call_sleeps_and_logs(settings, monkeypatch):
    slept: list = []
    monkeypatch.setattr(reddit_service.time, "sleep", lambda s: slept.append(s))
    logs: list = []
    reddit_service.pace_next_call(logs.append)
    assert len(slept) == 1 and slept[0] >= 2.0
    assert any("pacing" in m for m in logs)


def test_pace_next_call_noop_when_delay_zero(settings, monkeypatch):
    settings["reddit_request_delay_sec"] = "0"
    slept: list = []
    monkeypatch.setattr(reddit_service.time, "sleep", lambda s: slept.append(s))
    reddit_service.pace_next_call()
    assert slept == []


# --- first_definitive_problem ------------------------------------------------


def test_first_definitive_problem_returns_first_bad(monkeypatch):
    results = {
        "good": reddit_service.SubredditCheck(True, "ok", "ok", definitive=True),
        "bad": reddit_service.SubredditCheck(False, "not_found", "r/bad 404", definitive=True),
    }
    monkeypatch.setattr(reddit_service, "check_subreddit", lambda name, ua: results[name])

    problem = reddit_service.first_definitive_problem(["good", "bad"], UA)
    assert problem is not None and problem.status == "not_found"


def test_first_definitive_problem_none_when_all_ok_or_ambiguous(monkeypatch):
    results = {
        "good": reddit_service.SubredditCheck(True, "ok", "ok", definitive=True),
        "blocked": reddit_service.SubredditCheck(False, "forbidden", "ip block", definitive=False),
    }
    monkeypatch.setattr(reddit_service, "check_subreddit", lambda name, ua: results[name])

    assert reddit_service.first_definitive_problem(["good", "blocked"], UA) is None


# --- check_subreddit ---------------------------------------------------------


def test_check_subreddit_ok_via_rss(settings, monkeypatch):
    calls: list = []
    _patch_httpx(monkeypatch, calls, get_status=200)

    result = reddit_service.check_subreddit("SomeSub", UA)

    assert result.ok is True
    assert result.status == "ok"
    assert result.definitive is True
    get = next(c for c in calls if c[0] == "GET")
    assert get[1] == "https://www.reddit.com/r/SomeSub/new.rss"
    assert get[2] is None  # anonymous, no Authorization
    assert get[3] == {"limit": 1}  # lightweight: one entry


def test_check_subreddit_404_is_definitive_not_found(settings, monkeypatch):
    calls: list = []
    _patch_httpx(monkeypatch, calls, get_status=404)

    result = reddit_service.check_subreddit("Typooo", UA)

    assert result.ok is False
    assert result.status == "not_found"
    assert result.definitive is True  # this is what blocks a save


def test_check_subreddit_403_anonymous_is_ambiguous(settings, monkeypatch):
    # No credentials: a 403 on the public feed is usually an IP block, not proof
    # the sub is private — must NOT be definitive (would brick VPS deploys).
    calls: list = []
    _patch_httpx(monkeypatch, calls, get_status=403)

    result = reddit_service.check_subreddit("SomeSub", UA)

    assert result.ok is False
    assert result.status == "forbidden"
    assert result.definitive is False


def test_check_subreddit_403_with_credentials_is_definitive(settings, monkeypatch):
    settings["reddit_client_id"] = "cid"
    settings["reddit_client_secret"] = "secret"
    calls: list = []
    _patch_httpx(monkeypatch, calls, get_status=403)

    result = reddit_service.check_subreddit("PrivateSub", UA)

    assert result.ok is False
    assert result.status == "forbidden"
    assert result.definitive is True  # OAuth 403 = genuinely private/quarantined
    get = next(c for c in calls if c[0] == "GET")
    assert get[1] == "https://oauth.reddit.com/r/PrivateSub/about.json"


def test_check_subreddit_429_is_not_definitive(settings, monkeypatch):
    # Reddit rate-limiting the *check* itself must never block a save.
    calls: list = []
    _patch_httpx(monkeypatch, calls, get_status=429)

    result = reddit_service.check_subreddit("SomeSub", UA)

    assert result.ok is False
    assert result.status == "rate_limited"
    assert result.definitive is False


def test_check_subreddit_empty_input(settings):
    result = reddit_service.check_subreddit("   ", UA)
    assert result.ok is False
    assert result.status == "error"
    assert result.definitive is True


def test_check_subreddit_network_error_is_not_definitive(settings, monkeypatch):
    def boom(**kwargs):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(reddit_service.httpx, "Client", boom)

    result = reddit_service.check_subreddit("SomeSub", UA)

    assert result.ok is False
    assert result.status == "error"
    assert result.definitive is False


def test_check_subreddit_200_redirected_to_search_is_not_found(settings, monkeypatch):
    class RespWithUrl:
        status_code = 200
        url = "https://www.reddit.com/search?q=Typooo"

    monkeypatch.setattr(reddit_service.httpx, "Client", lambda **kw: _CtxClient(RespWithUrl()))

    result = reddit_service.check_subreddit("Typooo", UA)

    assert result.ok is False
    assert result.status == "not_found"
    assert result.definitive is True


class _CtxClient:
    """Minimal context-manager httpx.Client stub returning a fixed response."""

    def __init__(self, resp):
        self._resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, headers=None, params=None):
        return self._resp
