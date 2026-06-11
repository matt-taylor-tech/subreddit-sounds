"""Tests for Reddit access: public RSS by default, OAuth JSON when configured."""

import pytest

from app.services import reddit_service

UA = "web:listige-clone:0.1 (by /u/suiifelse)"

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
    def __init__(self, status, *, text="", payload=None):
        self.status_code = status
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"unexpected raise_for_status on {self.status_code}")


class FakeClient:
    """Records every request; returns RSS text for GETs, a token for POSTs."""

    def __init__(self, calls, *, get_status=200, get_text=ATOM, get_json=None, **kwargs):
        self._calls = calls
        self._get_status = get_status
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
        return FakeResp(self._get_status, text=self._get_text, payload=self._get_json)


@pytest.fixture
def settings(monkeypatch):
    store: dict[str, str] = {}
    monkeypatch.setattr(reddit_service.settings_service, "get", lambda k, d="": store.get(k, d))
    monkeypatch.setattr(reddit_service.settings_service, "put_many", lambda p: store.update(p))
    return store


def _patch_httpx(monkeypatch, calls, **resp):
    monkeypatch.setattr(
        reddit_service.httpx, "Client", lambda **kw: FakeClient(calls, **resp, **kw)
    )


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


def test_429_message_mentions_rate_limit(settings, monkeypatch):
    calls: list = []
    _patch_httpx(monkeypatch, calls, get_status=429)

    with pytest.raises(RuntimeError) as exc:
        reddit_service.fetch_posts("X", UA, "top", "week")

    assert "429" in str(exc.value)
    assert "rate" in str(exc.value).lower()
