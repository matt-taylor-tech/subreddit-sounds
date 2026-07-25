from app.services.reconcile import apply_blocklist, reconcile_latest_cap


def test_reconcile_prepends_new_items():
    out = reconcile_latest_cap(current_track_ids=["c1", "c2"], new_track_ids=["n1", "n2"], cap=10)
    assert out == ["n1", "n2", "c1", "c2"]


def test_reconcile_caps_size():
    out = reconcile_latest_cap(current_track_ids=["c1", "c2", "c3"], new_track_ids=["n1", "n2"], cap=3)
    assert out == ["n1", "n2", "c1"]


def test_reconcile_deduplicates_existing_track():
    out = reconcile_latest_cap(current_track_ids=["a", "b"], new_track_ids=["a"], cap=5)
    assert out == ["a", "b"]


def test_reconcile_deduplicates_within_new_tracks():
    out = reconcile_latest_cap(current_track_ids=["c"], new_track_ids=["a", "a", "b"], cap=5)
    assert out == ["a", "b", "c"]


# --- apply_blocklist (issue #11) ---------------------------------------------


def test_blocklist_detects_user_deletion():
    # X was in the playlist the app left last run (last_desired) but is gone now
    # -> the user removed it. It must be blocked and dropped from candidates.
    filtered, updated, newly = apply_blocklist(
        new_track_ids=["X", "Y"],
        current_track_ids=["Y"],  # X manually removed by the user
        last_desired_ids=["X", "Y"],
        blocked_ids=set(),
    )
    assert newly == {"X"}
    assert updated == {"X"}
    assert filtered == ["Y"]  # X not re-added


def test_blocklist_does_not_block_app_trimmed_track():
    # Z was trimmed by the app last run, so it was NOT in last_desired. It now
    # re-trends (in new_track_ids). It must NOT be blocked -> resurfacing intact.
    filtered, updated, newly = apply_blocklist(
        new_track_ids=["Z"],
        current_track_ids=["A"],
        last_desired_ids=["A"],  # Z is absent -> it was a trim, not a deletion
        blocked_ids=set(),
    )
    assert newly == set()
    assert filtered == ["Z"]  # resurfaces


def test_blocklist_excludes_already_blocked_from_candidates():
    filtered, updated, newly = apply_blocklist(
        new_track_ids=["B", "C"],
        current_track_ids=["C"],
        last_desired_ids=["C"],
        blocked_ids={"B"},  # previously blocked
    )
    assert newly == set()
    assert updated == {"B"}
    assert filtered == ["C"]  # B stays blocked


def test_blocklist_accumulates_across_runs():
    filtered, updated, newly = apply_blocklist(
        new_track_ids=["P", "Q", "R"],
        current_track_ids=["R"],  # Q just manually removed
        last_desired_ids=["Q", "R"],
        blocked_ids={"P"},  # P blocked earlier
    )
    assert newly == {"Q"}
    assert updated == {"P", "Q"}
    assert filtered == ["R"]
