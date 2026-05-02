from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.auth import hash_password
from app.config import settings
from app.db import Base, engine
from app.routes import router
from app.scheduler import SchedulerManager
from app.services.sync_service import SyncService


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)

    app.state.sync_service = SyncService()
    app.state.scheduler_manager = SchedulerManager(app.state.sync_service)
    app.state.admin_password_hash = hash_password(settings.admin_password)

    app.state.scheduler_manager.start()
    try:
        yield
    finally:
        app.state.scheduler_manager.shutdown()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
app.include_router(router)
