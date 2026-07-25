"""Minimal session-based CSRF protection for the admin forms.

A random token is stored in the session and mirrored into a hidden field on
every rendered form (via the ``csrf_context`` template context processor).
State-changing routes depend on ``verify_csrf``, which rejects any POST whose
submitted token doesn't match the session's.
"""

import secrets

from fastapi import HTTPException, Request, status

_SESSION_KEY = "csrf_token"
FORM_FIELD = "csrf_token"


def ensure_token(request: Request) -> str:
    """Return the session's CSRF token, creating one on first use."""
    token = request.session.get(_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[_SESSION_KEY] = token
    return token


def csrf_context(request: Request) -> dict:
    """Jinja context processor: expose ``csrf_token`` to every template."""
    return {"csrf_token": ensure_token(request)}


async def verify_csrf(request: Request) -> None:
    """FastAPI dependency: reject a state-changing request with a bad/missing token."""
    expected = request.session.get(_SESSION_KEY)
    form = await request.form()
    submitted = form.get(FORM_FIELD)
    if not expected or not submitted or not secrets.compare_digest(str(submitted), str(expected)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing CSRF token — reload the page and try again.",
        )
