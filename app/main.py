"""
SahyogSutra Main Application Factory.
Configures FastAPI, session middleware, lifespan handlers, static files,
error pages, route registrations, and Socket.IO ASGI integration.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
import socketio

from app.config import (
    SECRET_KEY,
    SESSION_MAX_AGE,
    SESSION_SAME_SITE,
    SESSION_HTTPS_ONLY
)
from app.database import (
    init_db_pool,
    close_db_pool,
    acquire_connection,
    release_connection,
    AsyncDB
)
from app.models import initialize_schema, migrate_legacy_messages
from app.services.email_service import close_http_client
from app.services.event_service import process_expired_events
from app.services.translation_service import (
    close_translation_client,
)

# Import route routers
from app.routes.auth import router as auth_router
from app.routes.events import router as events_router
from app.routes.admin import router as admin_router
from app.routes.chat import router as chat_router, sio
from app.routes.api import router as api_router

logger = logging.getLogger("sahyogsutra")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


async def expired_events_background_job():
    """Single, bounded background task to process expired events without self-HTTP requests."""
    while True:
        try:
            await asyncio.sleep(60)
            conn = acquire_connection()
            db = AsyncDB(conn)
            try:
                await process_expired_events(db)
            finally:
                db.close()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Error in expired events background job: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages application startup and graceful shutdown."""
    logger.info("Initializing SahyogSutra...")

    # 1. Initialize strictly bounded DB pool with 1 eager connection
    init_db_pool(eager_count=1)

    # 2. Initialize schema & migrate legacy data
    conn = acquire_connection()
    db = AsyncDB(conn)
    try:
        await initialize_schema(db)
        await migrate_legacy_messages(db)
        from app.routes.events import prewarm_event_count
        await prewarm_event_count(db)
    finally:
        db.close()

    # 3. Launch single background task for expired events
    task = asyncio.create_task(expired_events_background_job())

    logger.info("SahyogSutra startup completed successfully.")
    yield

    # Graceful Shutdown
    logger.info("Shutting down SahyogSutra...")
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    await close_http_client()
    await close_translation_client()
    close_db_pool()
    logger.info("SahyogSutra shutdown complete.")


# FastAPI Application
app = FastAPI(title="SahyogSutra", lifespan=lifespan)

# Secure Session Middleware
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    max_age=SESSION_MAX_AGE,
    same_site=SESSION_SAME_SITE,
    https_only=SESSION_HTTPS_ONLY
)

# Static files & templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# Exception Handlers
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return templates.TemplateResponse(request, "error.html", {
        "status_code": exc.status_code,
        "detail": exc.detail
    }, status_code=exc.status_code)


@app.exception_handler(500)
async def server_error_handler(request: Request, exc: Exception):
    logger.error("Unhandled 500 error: %s", exc)
    return templates.TemplateResponse(request, "error.html", {
        "status_code": 500,
        "detail": "Internal Server Error"
    }, status_code=500)


# Register Routers
app.include_router(auth_router)
app.include_router(events_router)
app.include_router(admin_router)
app.include_router(chat_router)
app.include_router(api_router)

from fastapi.responses import FileResponse
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/sahyog_sutra_logo.png")

# Wrap with Socket.IO ASGI application
asgi_app = socketio.ASGIApp(sio, other_asgi_app=app)

