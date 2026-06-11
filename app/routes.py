import secrets
import time
from datetime import datetime
from typing import List
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.auth import is_authenticated, verify_password
from app.db import get_db
from app.models import Run
from app.services import settings_service, spotify_service

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def require_auth(request: Request) -> None:
    if not is_authenticated(request):
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@router.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    stored_hash = settings_service.get("admin_password_hash")
    stored_username = settings_service.get("admin_username")
    if stored_hash and username == stored_username and verify_password(password, stored_hash):
        request.session["is_authenticated"] = True
        return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"}, status_code=401)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    require_auth(request)
    latest_run = db.query(Run).order_by(desc(Run.id)).first()
    next_run = request.app.state.scheduler_manager.next_run() if request.app.state.scheduler_manager else None

    playlist_name = None
    playlist_tracks = []
    playlist_id = settings_service.get("spotify_playlist_id")
    if spotify_service.is_connected() and playlist_id:
        try:
            playlist_name = spotify_service.get_playlist_name(playlist_id)
            track_ids = spotify_service.get_playlist_track_ids(playlist_id)
            info = spotify_service.get_tracks_info(track_ids)
            playlist_tracks = [info.get(tid, tid) for tid in track_ids]
        except Exception:
            pass

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "latest_run": latest_run,
            "next_run": next_run,
            "sync_timezone": settings_service.get("sync_timezone"),
            "sync_time": f"{int(settings_service.get('sync_hour')):02d}:{int(settings_service.get('sync_minute')):02d}",
            "spotify_connected": spotify_service.is_connected(),
            "playlist_name": playlist_name,
            "playlist_tracks": playlist_tracks,
            "playlist_id": playlist_id,
        },
    )


@router.get("/admin/runs")
def runs(request: Request, db: Session = Depends(get_db), run_id: int | None = None):
    require_auth(request)
    run_items = db.query(Run).order_by(desc(Run.id)).limit(100).all()
    return templates.TemplateResponse("runs.html", {"request": request, "runs": run_items, "highlight_run_id": run_id})


@router.post("/admin/run")
def run_now(request: Request, dry_run: bool = Form(False), db: Session = Depends(get_db)):
    require_auth(request)
    run_id = request.app.state.sync_service.run_once(db=db, trigger_type="manual", dry_run=dry_run)
    return RedirectResponse(url=f"/admin/runs?run_id={run_id}", status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------------------
# Spotify OAuth
# ---------------------------------------------------------------------------

@router.get("/spotify/authorize")
def spotify_authorize(request: Request):
    require_auth(request)
    state = secrets.token_urlsafe(16)
    request.session["spotify_state"] = state
    params = {
        "client_id": settings_service.get("spotify_client_id"),
        "response_type": "code",
        "redirect_uri": settings_service.get("spotify_redirect_uri"),
        "scope": spotify_service.SCOPES,
        "state": state,
    }
    return RedirectResponse(url=f"https://accounts.spotify.com/authorize?{urlencode(params)}")


@router.get("/callback")
def spotify_callback(
    request: Request,
    code: str | None = None,
    error: str | None = None,
    state: str | None = None,
):
    require_auth(request)
    expected = request.session.pop("spotify_state", None)
    if not expected or expected != state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state — please try again")
    if error:
        raise HTTPException(status_code=400, detail=f"Spotify denied access: {error}")
    spotify_service.exchange_code(code, settings_service.get("spotify_redirect_uri"))
    return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def _settings_context() -> dict:
    """Build the template context dict from current DB settings."""
    all_tags_str = settings_service.get("bandcamp_tags", settings_service.get("bandcamp_tag", ""))
    tag_list = [t.strip() for t in all_tags_str.split(",") if t.strip()]
    enabled_str = settings_service.get("bandcamp_enabled_tags", all_tags_str)
    enabled_set = {t.strip() for t in enabled_str.split(",") if t.strip()}
    return {
        "spotify_client_id": settings_service.get("spotify_client_id", ""),
        "spotify_client_secret": settings_service.get("spotify_client_secret", ""),
        "spotify_playlist_id": settings_service.get("spotify_playlist_id", ""),
        "spotify_redirect_uri": settings_service.get("spotify_redirect_uri", ""),
        "spotify_connected": spotify_service.is_connected(),
        "spotify_genre_filter": settings_service.get("spotify_genre_filter", ""),
        "reddit_subreddit": settings_service.get("reddit_subreddit", "MelodicDeathMetal"),
        "reddit_sort": settings_service.get("reddit_sort", "top"),
        "reddit_timeframe": settings_service.get("reddit_timeframe", "week"),
        "reddit_user_agent": settings_service.get("reddit_user_agent", ""),
        "reddit_client_id": settings_service.get("reddit_client_id", ""),
        "reddit_client_secret": settings_service.get("reddit_client_secret", ""),
        "sync_cap": settings_service.get("sync_cap", "25"),
        "min_track_duration_sec": settings_service.get("min_track_duration_sec", "120"),
        "sync_timezone": settings_service.get("sync_timezone", "America/New_York"),
        "sync_hour": settings_service.get("sync_hour", "7"),
        "sync_minute": settings_service.get("sync_minute", "0"),
        "bandcamp_enabled": settings_service.get("bandcamp_enabled", "false"),
        "bandcamp_tags": all_tags_str,
        "bandcamp_tag_list": tag_list,
        "bandcamp_enabled_set": enabled_set,
    }


@router.get("/admin/settings")
def settings_page(request: Request):
    require_auth(request)
    return templates.TemplateResponse(
        "settings.html",
        {"request": request, "settings": _settings_context(), "saved": False},
    )


@router.post("/admin/settings")
def settings_save(
    request: Request,
    spotify_client_id: str = Form(...),
    spotify_client_secret: str = Form(""),
    spotify_playlist_id: str = Form(...),
    spotify_redirect_uri: str = Form(...),
    spotify_genre_filter: str = Form(""),
    reddit_subreddit: str = Form(...),
    reddit_sort: str = Form("top"),
    reddit_timeframe: str = Form("week"),
    reddit_user_agent: str = Form(""),
    reddit_client_id: str = Form(""),
    reddit_client_secret: str = Form(""),
    sync_cap: int = Form(25),
    min_track_duration_sec: int = Form(120),
    sync_timezone: str = Form("America/New_York"),
    sync_hour: int = Form(7),
    sync_minute: int = Form(0),
    bandcamp_enabled: str = Form("false"),
    bc_tag_list: str = Form(""),
    bc_enabled: List[str] = Form(default=[]),
    new_bc_tag: str = Form(""),
):
    require_auth(request)

    # Build the full tag list: existing + any newly added
    existing = [t.strip() for t in bc_tag_list.split(",") if t.strip()]
    if new_bc_tag.strip():
        existing.append(new_bc_tag.strip())
    seen: set[str] = set()
    all_tags = [t for t in existing if not (t in seen or seen.add(t))]  # type: ignore[func-returns-value]

    updates = {
        "spotify_client_id": spotify_client_id.strip(),
        "spotify_playlist_id": spotify_playlist_id.strip(),
        "spotify_redirect_uri": spotify_redirect_uri.strip(),
        "spotify_genre_filter": spotify_genre_filter.strip(),
        "reddit_subreddit": reddit_subreddit.strip(),
        "reddit_sort": reddit_sort,
        "reddit_timeframe": reddit_timeframe,
        "reddit_client_id": reddit_client_id.strip(),
        "sync_cap": str(sync_cap),
        "min_track_duration_sec": str(max(0, min_track_duration_sec)),
        "sync_timezone": sync_timezone.strip(),
        "sync_hour": str(sync_hour),
        "sync_minute": str(sync_minute),
        "bandcamp_enabled": "true" if bandcamp_enabled == "true" else "false",
        "bandcamp_tags": ",".join(all_tags),
        "bandcamp_enabled_tags": ",".join(bc_enabled),
    }
    # Only overwrite the secret if a new one was provided
    if spotify_client_secret.strip():
        updates["spotify_client_secret"] = spotify_client_secret.strip()

    # Keep the existing User-Agent default if the field was cleared
    if reddit_user_agent.strip():
        updates["reddit_user_agent"] = reddit_user_agent.strip()

    # Reddit OAuth secret: only overwrite when provided. Whenever credentials
    # change, drop the cached app-only token so the next sync re-authenticates.
    if reddit_client_secret.strip():
        updates["reddit_client_secret"] = reddit_client_secret.strip()
    if reddit_client_id.strip() != settings_service.get("reddit_client_id") or reddit_client_secret.strip():
        updates["reddit_access_token"] = ""
        updates["reddit_token_expiry"] = "0"

    settings_service.put_many(updates)

    request.app.state.scheduler_manager.reschedule()

    return templates.TemplateResponse(
        "settings.html",
        {"request": request, "settings": _settings_context(), "saved": True},
    )
