from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import RedirectResponse

from app.config import settings
from app.db import Base, engine, run_migrations
from app.routes import router
from app.scheduler import SchedulerManager
from app.services.sync_service import SyncService
from app.setup_wizard import router as setup_router

_SETUP_BYPASS = {"/setup", "/healthz"}


class SetupRedirectMiddleware(BaseHTTPMiddleware):
    """Redirect every request to /setup until the wizard has been completed."""

    async def dispatch(self, request: StarletteRequest, call_next):
        path = request.url.path
        if path not in _SETUP_BYPASS:
            from app.services import settings_service  # avoid import cycle at module level

            if not settings_service.is_setup_complete():
                return RedirectResponse(url="/setup")
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    run_migrations()

    app.state.sync_service = SyncService()
    app.state.scheduler_manager = SchedulerManager(app.state.sync_service)

    app.state.scheduler_manager.start()
    try:
        yield
    finally:
        app.state.scheduler_manager.shutdown()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(SetupRedirectMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    same_site="lax",  # lax still allows the Spotify OAuth callback redirect
    https_only=settings.environment.lower() == "production",
)
app.include_router(setup_router)
app.include_router(router)
