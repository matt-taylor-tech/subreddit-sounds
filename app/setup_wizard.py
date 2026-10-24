from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import hash_password
from app.csrf import csrf_context, verify_csrf
from app.curated import curated_context
from app.services import settings_service
from app.timezones import is_valid_timezone
from app.version import version_context

router = APIRouter()
templates = Jinja2Templates(
    directory="app/templates", context_processors=[csrf_context, curated_context, version_context]
)

_DEFAULT_USER_AGENT = "web:subreddit-sounds:0.1 (by /u/suiifelse)"


@router.get("/setup")
def setup_page(request: Request):
    if settings_service.is_setup_complete():
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "setup.html", {"error": None})


@router.post("/setup")
def setup_submit(
    request: Request,
    _csrf: None = Depends(verify_csrf),
    admin_username: str = Form(...),
    admin_password: str = Form(...),
    admin_password_confirm: str = Form(...),
    reddit_sort: str = Form("top"),
    reddit_timeframe: str = Form("week"),
    reddit_user_agent: str = Form(""),
    reddit_client_id: str = Form(""),
    reddit_client_secret: str = Form(""),
    spotify_client_id: str = Form(...),
    spotify_client_secret: str = Form(...),
    spotify_redirect_uri: str = Form("http://127.0.0.1:8000/callback"),
    sync_timezone: str = Form("America/New_York"),
):
    """Store the admin login and the shared connection settings, nothing more.

    Playlists (targets) are created afterwards from the Playlists page, once
    Spotify is connected — so setup never has to invent a "Default" playlist.
    """
    if settings_service.is_setup_complete():
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    if admin_password != admin_password_confirm:
        return templates.TemplateResponse(
            request,
            "setup.html",
            {"error": "Passwords do not match"},
            status_code=400,
        )

    sync_timezone = sync_timezone.strip()
    if not is_valid_timezone(sync_timezone):
        return templates.TemplateResponse(
            request,
            "setup.html",
            {"error": f"Unknown timezone {sync_timezone!r}. Use an IANA name such as America/New_York."},
            status_code=400,
        )

    settings_service.put_many(
        {
            "admin_username": admin_username.strip(),
            "admin_password_hash": hash_password(admin_password),
            "reddit_sort": reddit_sort,
            "reddit_timeframe": reddit_timeframe,
            "reddit_user_agent": reddit_user_agent.strip() or _DEFAULT_USER_AGENT,
            "reddit_client_id": reddit_client_id.strip(),
            "reddit_client_secret": reddit_client_secret.strip(),
            "spotify_client_id": spotify_client_id.strip(),
            "spotify_client_secret": spotify_client_secret.strip(),
            "spotify_redirect_uri": spotify_redirect_uri.strip(),
            "sync_timezone": sync_timezone,
            "sync_enabled": "true",
        }
    )

    # Start the scheduler now that credentials are available.
    scheduler_manager = getattr(request.app.state, "scheduler_manager", None)
    if scheduler_manager:
        scheduler_manager.reschedule()

    # Whoever just set the admin password is the admin; don't make them type it
    # again. The dashboard walks them through connecting Spotify next.
    request.session["is_authenticated"] = True
    return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)
