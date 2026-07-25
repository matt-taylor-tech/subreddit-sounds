"""App version surfaced in the GUI (issue #41 part 1)."""

import tomllib
from pathlib import Path

from app.version import get_version


def test_get_version_matches_pyproject():
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    assert get_version() == expected
    assert get_version() != "unknown"
