"""Single source of truth for the app version, surfaced to templates.

The version lives in ``pyproject.toml``. We read it there at runtime (the app
runs from source, not as an installed distribution), preferring installed
package metadata if that ever changes. Never hardcode the version elsewhere.
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path

from fastapi import Request

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


@lru_cache(maxsize=1)
def get_version() -> str:
    # Prefer installed distribution metadata when available.
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("subreddit-sounds")
        except PackageNotFoundError:
            pass
    except Exception:
        pass

    # Fallback: read it from pyproject.toml (the canonical source when running
    # from source, which is how the Docker image runs).
    try:
        data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
        return data["project"]["version"]
    except Exception:
        return "unknown"


def version_context(request: Request) -> dict:
    """Jinja context processor: expose ``app_version`` to every template."""
    return {"app_version": get_version()}
