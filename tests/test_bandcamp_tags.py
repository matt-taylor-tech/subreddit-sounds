"""Bandcamp tag validation: taxonomy fast path, tag-index fallback, canonicalizing.

The network call is stubbed throughout, so these cover our own logic: which tags
short-circuit without a request, which get looked up, what counts as definitive
enough to block a save, and that a resolved tag is stored as Bandcamp's own slug.
"""

import httpx
import pytest

from app import bandcamp_taxonomy
from app.services import bandcamp_service


def _stub_autocomplete(monkeypatch, matches, *, raises=None):
    """Replace the tag-index lookup with canned matches; returns the call log."""
    calls = []

    def _fake(slug):
        calls.append(slug)
        if raises:
            raise raises
        return matches

    monkeypatch.setattr(bandcamp_service, "_fetch_tag_matches", _fake)
    return calls


def test_taxonomy_tag_needs_no_request(monkeypatch):
    calls = _stub_autocomplete(monkeypatch, [])
    result = bandcamp_service.check_tag("post-rock")
    assert result.ok and result.slug == "post-rock"
    assert calls == []  # picker options are known-good, so no network


def test_taxonomy_check_is_case_insensitive(monkeypatch):
    _stub_autocomplete(monkeypatch, [])
    assert bandcamp_service.check_tag("Post-Rock").slug == "post-rock"


def test_every_genre_and_subgenre_slug_is_known():
    # Guards the generated module: the picker must never offer a slug that our
    # own validator would then reject.
    for entry in bandcamp_taxonomy.GENRES + bandcamp_taxonomy.SUBGENRES:
        assert bandcamp_taxonomy.is_known(entry["slug"])


def test_unknown_tag_resolved_via_tag_index(monkeypatch):
    calls = _stub_autocomplete(monkeypatch, [{"norm_name": "post-rock", "display_name": "Post-rock"}])
    result = bandcamp_service.check_tag("Post Rock")
    assert result.ok
    assert result.slug == "post-rock"  # canonicalized to what the discover API wants
    assert calls == ["Post Rock"]


def test_nonexistent_tag_is_definitive(monkeypatch):
    _stub_autocomplete(monkeypatch, [])
    result = bandcamp_service.check_tag("zzzznotarealtag99")
    assert not result.ok and result.definitive
    assert result.reason == "not_found"


def test_network_failure_is_not_definitive(monkeypatch):
    _stub_autocomplete(monkeypatch, [], raises=httpx.ConnectError("boom"))
    result = bandcamp_service.check_tag("some-tag")
    assert not result.ok and not result.definitive


def test_empty_tag_rejected():
    assert bandcamp_service.check_tag("   ").reason == "empty"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("post-rock, shoegaze", ["post-rock", "shoegaze"]),
        ("  post-rock ,, shoegaze  ", ["post-rock", "shoegaze"]),
        ("post-rock, POST-ROCK", ["post-rock"]),  # de-duplicated case-insensitively
        ("", []),
    ],
)
def test_parse_tags(raw, expected):
    assert bandcamp_service.parse_tags(raw) == expected


def test_resolve_tags_reports_first_definitive_problem(monkeypatch):
    _stub_autocomplete(monkeypatch, [])  # nothing resolves via the index
    slugs, problem = bandcamp_service.resolve_tags(["post-rock", "notatag", "shoegaze"])
    assert problem is not None and "notatag" in problem.message
    assert slugs == ["post-rock", "shoegaze"]  # the bad one is dropped, order kept


def test_resolve_tags_keeps_order_and_canonicalizes(monkeypatch):
    _stub_autocomplete(monkeypatch, [{"norm_name": "darkwave"}])
    slugs, problem = bandcamp_service.resolve_tags(["shoegaze", "Dark Wave", "post-rock"])
    assert problem is None
    assert slugs == ["shoegaze", "darkwave", "post-rock"]


def test_resolve_tags_skips_grandfathered_values(monkeypatch):
    calls = _stub_autocomplete(monkeypatch, [])
    slugs, problem = bandcamp_service.resolve_tags(["legacy-custom-tag"], skip={"legacy-custom-tag"})
    assert problem is None
    assert slugs == ["legacy-custom-tag"]
    assert calls == []  # an already-saved tag isn't re-checked


def test_resolve_tags_keeps_tag_when_bandcamp_unreachable(monkeypatch):
    _stub_autocomplete(monkeypatch, [], raises=httpx.ConnectError("boom"))
    slugs, problem = bandcamp_service.resolve_tags(["something-odd"])
    assert problem is None  # ambiguous, so the save proceeds
    assert slugs == ["something-odd"]
