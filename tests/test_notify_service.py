"""Failure-notification webhook (issue #13)."""

import httpx
import pytest

from app.services import notify_service


class _Run:
    id = 7
    status = "failed"
    trigger_type = "scheduled"
    message = "RuntimeError: boom"


class _FakeClient:
    def __init__(self, calls, *, boom=False):
        self._calls = calls
        self._boom = boom

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, json=None):
        if self._boom:
            raise httpx.ConnectError("unreachable")
        self._calls.append((url, json))


@pytest.fixture
def store(monkeypatch):
    data: dict[str, str] = {}
    monkeypatch.setattr(notify_service.settings_service, "get", lambda k, d="": data.get(k, d))
    return data


def test_no_webhook_is_noop(store, monkeypatch):
    called = []
    monkeypatch.setattr(notify_service.httpx, "Client", lambda **kw: _FakeClient(called))
    notify_service.notify_run_failed(_Run())
    assert called == []  # nothing posted when unconfigured
    assert notify_service.is_configured() is False


def test_posts_failure_payload_when_configured(store, monkeypatch):
    store["notify_webhook_url"] = "https://hook.example/abc"
    calls: list = []
    monkeypatch.setattr(notify_service.httpx, "Client", lambda **kw: _FakeClient(calls))

    notify_service.notify_run_failed(_Run())

    assert len(calls) == 1
    url, payload = calls[0]
    assert url == "https://hook.example/abc"
    # Same message under both Discord (content) and Slack (text) keys.
    assert "run #7 FAILED" in payload["content"]
    assert payload["content"] == payload["text"]
    assert payload["run_id"] == 7
    assert payload["message"] == "RuntimeError: boom"
    assert "boom" in payload["content"]


def test_notification_failure_is_swallowed(store, monkeypatch):
    store["notify_webhook_url"] = "https://hook.example/abc"
    monkeypatch.setattr(notify_service.httpx, "Client", lambda **kw: _FakeClient([], boom=True))
    # Must not raise even though the POST blows up.
    notify_service.notify_run_failed(_Run())
