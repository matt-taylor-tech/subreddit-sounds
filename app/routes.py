import secrets
import time
from datetime import datetime
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
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "latest_run": latest_run,
            "next_run": next_run,
            "sync_timezone": settings_service.get("sync_timezone"),
            "sync_time": f"{int(settings_service.get('sync_hour')):02d}:{int(settings_service.get('sync_minute')):02d}",
            "spotify_connected": spotify_service.is_connected(),
        },
    )


@router.get("/admin/runs")
def runs(request: Request, db: Session = Depends(get_db)):
    require_auth(request)
    run_items = db.query(Run).order_by(desc(Run.id)).limit(100).all()
    return templates.TemplateResponse("runs.html", {"request": request, "runs": run_items})


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
