import json
import secrets
from datetime import datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app import login_throttle
from app.auth import is_authenticated, verify_password
from app.csrf import csrf_context, verify_csrf
from app.curated import curated_context
from app.db import get_db
from app.models import Run
from app.services import config_io, reddit_service, settings_service, spotify_service, targets_service
from app.version import version_context

router = APIRouter()
templates = Jinja2Templates(
    directory="app/templates", context_processors=[csrf_context, curated_context, version_context]
)


def require_auth(request: Request) -> None:
    if not is_authenticated(request):
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@router.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    _csrf: None = Depends(verify_csrf),
):
    locked_for = login_throttle.seconds_remaining(request)
    if locked_for > 0:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": f"Too many failed attempts. Try again in {int(locked_for) + 1}s."},
            status_code=429,
        )
    stored_hash = settings_service.get("admin_password_hash")
    stored_username = settings_service.get("admin_username")
    if stored_hash and username == stored_username and verify_password(password, stored_hash):
        login_throttle.reset(request)
        request.session["is_authenticated"] = True
        return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    login_throttle.record_failure(request)
    return templates.TemplateResponse(request, "login.html", {"error": "Invalid credentials"}, status_code=401)


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
    mgr = getattr(request.app.state, "scheduler_manager", None)
    next_runs = mgr.next_runs() if mgr else {}
    connected = spotify_service.is_connected()

    views = []
    for target in targets_service.list_targets(db):
        latest_run = db.query(Run).filter(Run.target_id == target.id).order_by(desc(Run.id)).first()
        playlist_name = None
        playlist_tracks: list = []
        if connected and target.playlist_id:
            try:
                playlist_name = spotify_service.get_playlist_name(target.playlist_id)
                track_ids = spotify_service.get_playlist_track_ids(target.playlist_id)
                info = spotify_service.get_tracks_info(track_ids)
                playlist_tracks = [info.get(tid, tid) for tid in track_ids]
            except Exception:
                pass
        views.append(
            {
                "target": target,
                "latest_run": latest_run,
                "next_run": next_runs.get(target.id),
                "playlist_name": playlist_name,
                "playlist_tracks": playlist_tracks,
            }
        )

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "spotify_connected": connected,
            "sync_timezone": settings_service.get("sync_timezone"),
            "views": views,
        },
    )


@router.get("/admin/runs")
def runs(request: Request, db: Session = Depends(get_db), run_id: int | None = None):
    require_auth(request)
    run_items = db.query(Run).order_by(desc(Run.id)).limit(100).all()
    return templates.TemplateResponse(request, "runs.html", {"runs": run_items, "highlight_run_id": run_id})


@router.post("/admin/run")
def run_now(
    request: Request,
    dry_run: bool = Form(False),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    require_auth(request)
    run_ids = request.app.state.sync_service.run_all(db=db, trigger_type="manual", dry_run=dry_run)
    if run_ids:
        return RedirectResponse(url=f"/admin/runs?run_id={run_ids[0]}", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/admin/runs", status_code=status.HTTP_303_SEE_OTHER)


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
    """Global (non-target) settings for the Settings page. Per-target config
    lives on the targets pages."""
    return {
        "spotify_client_id": settings_service.get("spotify_client_id", ""),
        "spotify_client_secret": settings_service.get("spotify_client_secret", ""),
        "spotify_redirect_uri": settings_service.get("spotify_redirect_uri", ""),
        "spotify_connected": spotify_service.is_connected(),
        "reddit_sort": settings_service.get("reddit_sort", "top"),
        "reddit_timeframe": settings_service.get("reddit_timeframe", "week"),
        "reddit_user_agent": settings_service.get("reddit_user_agent", ""),
        "reddit_client_id": settings_service.get("reddit_client_id", ""),
        "reddit_client_secret": settings_service.get("reddit_client_secret", ""),
        "min_track_duration_sec": settings_service.get("min_track_duration_sec", "120"),
        "sync_timezone": settings_service.get("sync_timezone", "America/New_York"),
        "sync_enabled": settings_service.get("sync_enabled", "true"),
        "notify_webhook_url": settings_service.get("notify_webhook_url", ""),
    }


@router.get("/admin/settings")
def settings_page(request: Request):
    require_auth(request)
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"settings": _settings_context(), "saved": False},
    )


@router.post("/admin/settings")
def settings_save(
    request: Request,
    _csrf: None = Depends(verify_csrf),
    spotify_client_id: str = Form(...),
    spotify_client_secret: str = Form(""),
    spotify_redirect_uri: str = Form(...),
    reddit_sort: str = Form("top"),
    reddit_timeframe: str = Form("week"),
    reddit_user_agent: str = Form(""),
    reddit_client_id: str = Form(""),
    reddit_client_secret: str = Form(""),
    min_track_duration_sec: int = Form(120),
    sync_timezone: str = Form("America/New_York"),
    sync_enabled: str = Form("false"),
    notify_webhook_url: str = Form(""),
):
    require_auth(request)

    updates = {
        "spotify_client_id": spotify_client_id.strip(),
        "spotify_redirect_uri": spotify_redirect_uri.strip(),
        "reddit_sort": reddit_sort,
        "reddit_timeframe": reddit_timeframe,
        "reddit_client_id": reddit_client_id.strip(),
        "notify_webhook_url": notify_webhook_url.strip(),
        "min_track_duration_sec": str(max(0, min_track_duration_sec)),
        "sync_timezone": sync_timezone.strip(),
        "sync_enabled": "true" if sync_enabled == "true" else "false",
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
        request,
        "settings.html",
        {"settings": _settings_context(), "saved": True},
    )


@router.post("/admin/settings/export")
def settings_export(
    request: Request,
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
    include_secrets: str = Form("false"),
):
    require_auth(request)
    data = config_io.export_config(db, include_secrets=include_secrets == "true")
    body = json.dumps(data, indent=2)
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="subreddit-sounds-settings.json"'},
    )


@router.post("/admin/settings/import")
def settings_import(
    request: Request,
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
    file: UploadFile = File(...),
):
    require_auth(request)
    try:
        data = json.loads(file.file.read())
        config_io.import_config(db, data)
    except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
        return templates.TemplateResponse(
            request,
            "settings.html",
            {"settings": _settings_context(), "saved": False, "error": f"Import failed: {exc}"},
            status_code=400,
        )
    request.app.state.scheduler_manager.reschedule()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"settings": _settings_context(), "saved": True, "imported": True},
    )


# ---------------------------------------------------------------------------
# Targets (playlists)
# ---------------------------------------------------------------------------

_NEW_FORM = {
    "name": "",
    "playlist_id": "",
    "subreddits": "",
    "genre_filter": "",
    "cap": 25,
    "bandcamp_enabled": False,
    "bandcamp_tags": "",
    "sync_hour": 7,
    "sync_minute": 0,
    "blocklist_enabled": False,
}


def _form_from_target(t) -> dict:
    return {
        "name": t.name,
        "playlist_id": t.playlist_id,
        "subreddits": t.subreddits,
        "genre_filter": t.genre_filter or "",
        "cap": t.cap,
        "bandcamp_enabled": t.bandcamp_enabled,
        "bandcamp_tags": t.bandcamp_tags,
        "sync_hour": t.sync_hour,
        "sync_minute": t.sync_minute,
        "blocklist_enabled": t.blocklist_enabled,
    }


def _blocked_tracks(target) -> list[tuple[str, str]]:
    """Blocked track ids resolved to 'Artist — Title' where possible."""
    ids = [i.strip() for i in target.blocklist_ids.split(",") if i.strip()]
    if not ids:
        return []
    info: dict = {}
    if spotify_service.is_connected():
        try:
            info = spotify_service.get_tracks_info(ids)
        except Exception:
            info = {}
    return [(i, info.get(i, i)) for i in ids]


def _validate_target_form(db, form: dict, existing=None) -> tuple[dict | None, str | None]:
    """Validate submitted target fields; return (fields_to_save, error)."""
    subs = reddit_service.parse_subreddits(form["subreddits"])
    if not form["playlist_id"].strip():
        return None, "Playlist ID is required."
    if not subs:
        return None, "Enter at least one subreddit."
    # Verify only newly-added subreddits (spare Reddit's rate limit).
    current = {s.lower() for s in reddit_service.parse_subreddits(existing.subreddits)} if existing else set()
    added = [s for s in subs if s.lower() not in current]
    if added:
        problem = reddit_service.first_definitive_problem(added, settings_service.get("reddit_user_agent"))
        if problem:
            return None, problem.message
    tags = ",".join(t.strip() for t in form["bandcamp_tags"].split(",") if t.strip())
    fields = {
        "name": form["name"].strip() or "Playlist",
        "playlist_id": form["playlist_id"].strip(),
        "subreddits": ", ".join(subs),
        "genre_filter": form["genre_filter"].strip() or None,
        "cap": form["cap"],
        "bandcamp_enabled": form["bandcamp_enabled"] == "true",
        "bandcamp_tags": tags,
        "bandcamp_enabled_tags": tags,
        "sync_hour": form["sync_hour"],
        "sync_minute": form["sync_minute"],
        "blocklist_enabled": form["blocklist_enabled"] == "true",
    }
    return fields, None


def _reschedule(request: Request) -> None:
    mgr = getattr(request.app.state, "scheduler_manager", None)
    if mgr:
        mgr.reschedule()


@router.get("/admin/targets")
def targets_list(request: Request, db: Session = Depends(get_db)):
    require_auth(request)
    targets = targets_service.list_targets(db)
    mgr = getattr(request.app.state, "scheduler_manager", None)
    next_runs = mgr.next_runs() if mgr else {}
    return templates.TemplateResponse(request, "targets.html", {"targets": targets, "next_runs": next_runs})


@router.get("/admin/targets/new")
def target_new(request: Request):
    require_auth(request)
    return templates.TemplateResponse(
        request, "target_form.html", {"form": dict(_NEW_FORM), "action": "/admin/targets", "error": None}
    )


@router.get("/admin/targets/{target_id}/edit")
def target_edit(request: Request, target_id: int, db: Session = Depends(get_db)):
    require_auth(request)
    target = targets_service.get_target(db, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Target not found")
    return templates.TemplateResponse(
        request,
        "target_form.html",
        {
            "form": _form_from_target(target),
            "action": f"/admin/targets/{target_id}",
            "target_id": target_id,
            "blocked_tracks": _blocked_tracks(target),
            "error": None,
        },
    )


def _form_params(
    name: str = Form(""),
    playlist_id: str = Form(""),
    subreddits: str = Form(""),
    genre_filter: str = Form(""),
    cap: int = Form(25),
    bandcamp_enabled: str = Form("false"),
    bandcamp_tags: str = Form(""),
    sync_hour: int = Form(7),
    sync_minute: int = Form(0),
    blocklist_enabled: str = Form("false"),
) -> dict:
    return {
        "name": name,
        "playlist_id": playlist_id,
        "subreddits": subreddits,
        "genre_filter": genre_filter,
        "cap": cap,
        "bandcamp_enabled": bandcamp_enabled,
        "bandcamp_tags": bandcamp_tags,
        "sync_hour": sync_hour,
        "sync_minute": sync_minute,
        "blocklist_enabled": blocklist_enabled,
    }


@router.post("/admin/targets")
def target_create(
    request: Request,
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
    form: dict = Depends(_form_params),
):
    require_auth(request)
    fields, error = _validate_target_form(db, form)
    if error:
        return templates.TemplateResponse(
            request,
            "target_form.html",
            {"form": form, "action": "/admin/targets", "error": error},
            status_code=400,
        )
    targets_service.create_target(db, **fields)
    _reschedule(request)
    return RedirectResponse(url="/admin/targets", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/targets/{target_id}")
def target_update(
    request: Request,
    target_id: int,
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
    form: dict = Depends(_form_params),
):
    require_auth(request)
    target = targets_service.get_target(db, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Target not found")
    fields, error = _validate_target_form(db, form, existing=target)
    if error:
        return templates.TemplateResponse(
            request,
            "target_form.html",
            {
                "form": form,
                "action": f"/admin/targets/{target_id}",
                "target_id": target_id,
                "blocked_tracks": _blocked_tracks(target),
                "error": error,
            },
            status_code=400,
        )
    targets_service.update_target(db, target_id, **fields)
    _reschedule(request)
    return RedirectResponse(url="/admin/targets", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/targets/{target_id}/delete")
def target_delete(request: Request, target_id: int, db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    require_auth(request)
    targets_service.delete_target(db, target_id)
    _reschedule(request)
    return RedirectResponse(url="/admin/targets", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/targets/{target_id}/toggle")
def target_toggle(request: Request, target_id: int, db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    require_auth(request)
    target = targets_service.get_target(db, target_id)
    if target is not None:
        targets_service.update_target(db, target_id, enabled=not target.enabled)
        _reschedule(request)
    return RedirectResponse(url="/admin/targets", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/targets/{target_id}/run")
def target_run(
    request: Request,
    target_id: int,
    dry_run: bool = Form(False),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    require_auth(request)
    target = targets_service.get_target(db, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Target not found")
    run_id = request.app.state.sync_service.run_once(db=db, target=target, trigger_type="manual", dry_run=dry_run)
    if run_id is not None:
        return RedirectResponse(url=f"/admin/runs?run_id={run_id}", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/admin/runs", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/targets/{target_id}/blocklist/remove")
def target_blocklist_remove(
    request: Request,
    target_id: int,
    track_id: str = Form(...),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    require_auth(request)
    target = targets_service.get_target(db, target_id)
    if target is not None:
        remaining = [i.strip() for i in target.blocklist_ids.split(",") if i.strip() and i.strip() != track_id]
        targets_service.update_target(db, target_id, blocklist_ids=",".join(remaining))
    return RedirectResponse(url=f"/admin/targets/{target_id}/edit", status_code=status.HTTP_303_SEE_OTHER)
