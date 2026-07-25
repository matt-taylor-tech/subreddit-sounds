def reconcile_latest_cap(current_track_ids: list[str], new_track_ids: list[str], cap: int) -> list[str]:
    """Return newest-first list with new items prepended, deduped, and capped in size."""
    seen: set[str] = set()
    result: list[str] = []
    for tid in list(new_track_ids) + list(current_track_ids):
        if tid not in seen:
            seen.add(tid)
            result.append(tid)
    return result[:cap]


def apply_blocklist(
    new_track_ids: list[str],
    current_track_ids: list[str],
    last_desired_ids: list[str],
    blocked_ids: set[str],
) -> tuple[list[str], set[str], set[str]]:
    """Detect user deletions and drop blocked tracks from the run's candidates.

    Returns ``(filtered_new_ids, updated_blocked, newly_blocked)``.

    A track the app intends to keep goes into its *desired* set and is written to
    the playlist; a track the app *trims* (cap overflow) is excluded from desired.
    So anything in the previous run's desired set that's now missing from the
    playlist was removed by the user, not trimmed by the app — those are the
    "newly blocked" deletions. Trimmed tracks were never in ``last_desired``, so
    they are never blocked and can still resurface if they re-trend.

    Blocked IDs are removed only from the *candidates* (never re-added). A blocked
    track the user manually re-adds stays — we don't fight a deliberate re-add.
    """
    newly_blocked = set(last_desired_ids) - set(current_track_ids)
    updated_blocked = set(blocked_ids) | newly_blocked
    filtered = [tid for tid in new_track_ids if tid not in updated_blocked]
    return filtered, updated_blocked, newly_blocked
