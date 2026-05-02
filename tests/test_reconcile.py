from app.services.reconcile import reconcile_latest_cap


def test_reconcile_prepends_new_items():
    out = reconcile_latest_cap(current_track_ids=["c1", "c2"], new_track_ids=["n1", "n2"], cap=10)
    assert out == ["n1", "n2", "c1", "c2"]


def test_reconcile_caps_size():
    out = reconcile_latest_cap(current_track_ids=["c1", "c2", "c3"], new_track_ids=["n1", "n2"], cap=3)
    assert out == ["n1", "n2", "c1"]


def test_reconcile_allows_duplicates():
    out = reconcile_latest_cap(current_track_ids=["a", "b"], new_track_ids=["a"], cap=5)
    assert out == ["a", "a", "b"]
