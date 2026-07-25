from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import hash_password
from app.csrf import csrf_context, verify_csrf
from app.curated import curated_context
from app.services import reddit_service, settings_service

router = APIRouter()
templates = Jinja2Templates(directory="app/templates", context_processors=[csrf_context, curated_context])

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
    reddit_subreddit: str = Form(...),
    reddit_sort: str = Form("top"),
    reddit_timeframe: str = Form("week"),
    reddit_user_agent: str = Form(""),
    reddit_client_id: str = Form(""),
    reddit_client_secret: str = Form(""),
    spotify_client_id: str = Form(...),
    spotify_client_secret: str = Form(...),
    spotify_playlist_id: str = Form(...),
    spotify_redirect_uri: str = Form("http://127.0.0.1:8000/callback"),
    sync_cap: int = Form(25),
    sync_timezone: str = Form("America/New_York"),
    sync_hour: int = Form(7),
    sync_minute: int = Form(0),
    spotify_genre_filter: str = Form(""),
    bandcamp_enabled: str = Form("false"),
    bandcamp_tag: str = Form(""),
):
    if settings_service.is_setup_complete():
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    if admin_password != admin_password_confirm:
        return templates.TemplateResponse(
            request,
            "setup.html",
            {"error": "Passwords do not match"},
            status_code=400,
        )

    subreddits = reddit_service.parse_subreddits(reddit_subreddit)
    if not subreddits:
        return templates.TemplateResponse(
            request,
            "setup.html",
            {"error": "Enter at least one subreddit."},
            status_code=400,
        )
    user_agent = reddit_user_agent.strip() or _DEFAULT_USER_AGENT
    problem = reddit_service.first_definitive_problem(subreddits, user_agent)
    if problem:
        return templates.TemplateResponse(
            request,
            "setup.html",
            {"error": problem.message},
            status_code=400,
        )

    settings_service.put_many(
        {
            "admin_username": admin_username,
            "admin_password_hash": hash_password(admin_password),
            "reddit_subreddit": ", ".join(subreddits),
            "reddit_sort": reddit_sort,
            "reddit_timeframe": reddit_timeframe,
            "reddit_user_agent": user_agent,
            "reddit_client_id": reddit_client_id.strip(),
            "reddit_client_secret": reddit_client_secret.strip(),
            "spotify_client_id": spotify_client_id,
            "spotify_client_secret": spotify_client_secret,
            "spotify_playlist_id": spotify_playlist_id,
            "spotify_redirect_uri": spotify_redirect_uri,
            "sync_cap": str(sync_cap),
            "sync_timezone": sync_timezone,
            "sync_hour": str(sync_hour),
            "sync_minute": str(sync_minute),
            "sync_enabled": "true",
            "spotify_genre_filter": spotify_genre_filter.strip(),
            "bandcamp_enabled": "true" if bandcamp_enabled == "true" else "false",
            "bandcamp_tag": bandcamp_tag.strip(),
        }
    )

    # Start the daily scheduler now that credentials are available.
    scheduler_manager = getattr(request.app.state, "scheduler_manager", None)
    if scheduler_manager:
        scheduler_manager.reschedule()

    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
