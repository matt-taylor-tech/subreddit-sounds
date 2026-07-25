"""Per-target locking (issue #17): distinct targets sync concurrently; a single
target never double-writes."""

from app.services.sync_service import SyncService


def test_per_target_locks_are_independent():
    s = SyncService()
    la = s._lock_for(1)
    lb = s._lock_for(2)
    assert la is not lb
    assert s._lock_for(1) is la  # same target id -> same lock instance

    la.acquire()
    try:
        # Same target is busy -> a second run would no-op.
        assert la.acquire(blocking=False) is False
        # A different target is unaffected -> runs concurrently.
        assert lb.acquire(blocking=False) is True
        lb.release()
    finally:
        la.release()
