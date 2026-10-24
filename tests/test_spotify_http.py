"""Request shaping in the Spotify client, against a fake httpx.Client."""

from app.services import spotify_service


class _Resp:
    def __init__(self, data=None):
        self._data = data or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class _FakeClient:
    """Records every call; answers searches with ``search_items``."""

    def __init__(self, search_items=None):
        self.calls: list[tuple[str, str, dict]] = []
        self.search_items = search_items or []

    def __call__(self, *args, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return _Resp()

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        if url.endswith("/search"):
            return _Resp({"tracks": {"items": self.search_items}})
        return _Resp({"artists": []})


def _patch(monkeypatch, fake):
    monkeypatch.setattr(spotify_service.httpx, "Client", fake)
    monkeypatch.setattr(spotify_service, "get_access_token", lambda: "tok")


def test_add_tracks_keeps_order_across_batches(monkeypatch):
    fake = _FakeClient()
    _patch(monkeypatch, fake)
    ids = [f"t{i}" for i in range(250)]
    spotify_service.add_tracks("PL", ids)
    positions = [kw["json"]["position"] for _, _, kw in fake.calls]
    assert positions == [0, 100, 200]
    assert fake.calls[1][2]["json"]["uris"][0] == "spotify:track:t100"


def test_artist_genre_lookup_is_batched_at_50(monkeypatch):
    items = [
        {"id": f"tr{n}", "name": "Song", "artists": [{"id": f"a{n}-{k}", "name": f"A{n}"} for k in range(6)]}
        for n in range(10)
    ]  # 60 distinct artists
    fake = _FakeClient(search_items=items)
    _patch(monkeypatch, fake)
    spotify_service._search_and_select(
        "q", query="Song", artist=None, genre_filter="metal", min_duration_ms=None, artist_is_hint=True
    )
    artist_calls = [kw["params"]["ids"].split(",") for _, url, kw in fake.calls if url.endswith("/artists")]
    assert [len(batch) for batch in artist_calls] == [50, 10]
