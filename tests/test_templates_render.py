"""Smoke tests that the HTML templates actually render end-to-end.

These guard against regressions in the ``TemplateResponse`` call signature and
the Jinja context processors (csrf, curated lists). Every other test exercises
services or dependencies in isolation and never renders a page, so a broken
template render would otherwise ship silently.
"""

import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def test_setup_page_renders():
    # Fresh DB => setup not complete => the wizard renders (not a redirect).
    with TestClient(app) as client:
        r = client.get("/setup")
        assert r.status_code == 200
        assert "First-Time Setup" in r.text
        # csrf context processor ran
        assert 'name="csrf_token"' in r.text


def test_login_page_renders():
    with TestClient(app) as client:
        r = client.get("/login")
        assert r.status_code == 200
        assert 'name="csrf_token"' in r.text
