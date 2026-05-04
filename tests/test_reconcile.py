from app.services.reconcile import reconcile_latest_cap


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
