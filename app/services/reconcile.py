def reconcile_latest_cap(current_track_ids: list[str], new_track_ids: list[str], cap: int) -> list[str]:
    """Return newest-first list with new items prepended, deduped, and capped in size."""
    seen: set[str] = set()
    result: list[str] = []
    for tid in list(new_track_ids) + list(current_track_ids):
        if tid not in seen:
            seen.add(tid)
            result.append(tid)
    return result[:cap]
