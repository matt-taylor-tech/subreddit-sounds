"""In-memory failed-login throttling.

Tracks recent failed login attempts per client IP and locks out further
attempts for a cooldown once a threshold is exceeded. State is in-memory, so it
resets on restart — fine for a single-admin self-hosted app. Behind a reverse
proxy that doesn't forward the real client IP, this degrades to a global lock,
which is acceptable here (there's only one admin).
"""

import time
from threading import Lock

from fastapi import Request

MAX_FAILURES = 5
LOCKOUT_SECONDS = 300  # 5 minutes

_lock = Lock()
_failures: dict[str, list[float]] = {}  # client ip -> recent failure timestamps


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _recent(ip: str, now: float) -> list[float]:
    return [t for t in _failures.get(ip, []) if now - t < LOCKOUT_SECONDS]


def seconds_remaining(request: Request) -> float:
    """Return remaining lockout seconds for this client (0.0 if not locked)."""
    now = time.time()
    ip = _client_ip(request)
    with _lock:
        times = _recent(ip, now)
        _failures[ip] = times
        if len(times) >= MAX_FAILURES:
            return LOCKOUT_SECONDS - (now - times[0])
    return 0.0


def record_failure(request: Request) -> None:
    now = time.time()
    ip = _client_ip(request)
    with _lock:
        _failures[ip] = _recent(ip, now) + [now]


def reset(request: Request) -> None:
    with _lock:
        _failures.pop(_client_ip(request), None)
