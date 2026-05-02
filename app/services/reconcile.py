def reconcile_latest_cap(current_track_ids: list[str], new_track_ids: list[str], cap: int) -> list[str]:
    """Return newest-first list with new items prepended and capped in size.

    Duplicates are allowed intentionally by product requirement.
    """
    merged = list(new_track_ids) + list(current_track_ids)
    return merged[:cap]
