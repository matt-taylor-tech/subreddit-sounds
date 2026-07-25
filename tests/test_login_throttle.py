"""Failed-login throttling: lockout after repeated failures, expiry, isolation."""

import time

import pytest

import app.login_throttle as lt


class FakeReq:
    def __init__(self, host: str = "1.2.3.4"):
        self.client = type("Client", (), {"host": host})()


@pytest.fixture(autouse=True)
def _clear_state():
    lt._failures.clear()
    yield
    lt._failures.clear()


def test_not_locked_before_threshold():
    req = FakeReq()
    for _ in range(lt.MAX_FAILURES - 1):
        lt.record_failure(req)
    assert lt.seconds_remaining(req) == 0.0


def test_locks_after_max_failures():
    req = FakeReq()
    for _ in range(lt.MAX_FAILURES):
        lt.record_failure(req)
    assert lt.seconds_remaining(req) > 0


def test_reset_clears_lock():
    req = FakeReq()
    for _ in range(lt.MAX_FAILURES):
        lt.record_failure(req)
    lt.reset(req)
    assert lt.seconds_remaining(req) == 0.0


def test_old_failures_expire():
    req = FakeReq()
    past = time.time() - (lt.LOCKOUT_SECONDS + 1)
    lt._failures[req.client.host] = [past] * lt.MAX_FAILURES
    assert lt.seconds_remaining(req) == 0.0


def test_separate_ips_are_independent():
    a, b = FakeReq("1.1.1.1"), FakeReq("2.2.2.2")
    for _ in range(lt.MAX_FAILURES):
        lt.record_failure(a)
    assert lt.seconds_remaining(a) > 0
    assert lt.seconds_remaining(b) == 0.0
