"""Timezone validation shared by the setup wizard and the settings page.

An unknown zone name makes APScheduler's ``CronTrigger`` raise, which used to
surface as a 500 on save and then stop the app booting at all (the scheduler
re-reads the stored zone on startup). Validate before anything is persisted.
"""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def is_valid_timezone(name: str) -> bool:
    if not name:
        return False
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True
