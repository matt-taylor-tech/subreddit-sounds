"""Current time as naive UTC, matching what the database stores.

``datetime.utcnow()`` is deprecated. Columns are naive (SQLite has no time
zone), so swapping in an aware ``datetime.now(UTC)`` would make every
comparison with a stored value raise ``TypeError``. This keeps the stored
representation unchanged.
"""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
