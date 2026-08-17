"""FastAPI application: wires config, database, the Mercari monitoring
pipeline, the REST API, and the WebSocket bridge together.

Startup order matters: logging first (so nothing before it is silently
swallowed), then the database (everything else depends on being able to
read/write it), then the Mercari browser client (slow — launches Chromium),
then the services that depend on it, and only then do we start scanning.
Shutdown reverses this so nothing tries to use a resource that's already
gone (spec section 34/35 — clean shutdown, crash recovery on next start).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.api.websocket import handle_websocket, register_event_bridge
from app.config.settings import settings
from app.database.database import dispose_engine, init_db
from app.mercari.client import MercariClient
from app.mercari.search import MercariUSSource
from app.services.keyword_service import DuplicateKeywordError
from app.services.monitoring_service import MonitoringService
from app.services.notification_service import notification_service
from app.utils.logger import get_logger, setup_logging
from app.utils.validation import ValidationError

setup_logging()
logger = get_logger(__name__)

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Mercari US Monitor initializing...")

    await init_db()
    logger.info("Database          OK")

    client = MercariClient()
    await client.start()
    source = MercariUSSource(client)
    logger.info("Mercari source    OK (real-browser client started)")

    monitoring_service = MonitoringService(source)
    app.state.monitoring_service = monitoring_service
    app.state.mercari_client = client

    register_event_bridge()
    logger.info("WebSocket         OK")

    notification_service.start()
    logger.info(
        "Discord           %s",
        "configured" if settings.has_discord else "not configured (set DISCORD_WEBHOOK_URL in .env)",
    )

    await monitoring_service.start()
    logger.info("Workers           %d active", monitoring_service.active_worker_count())
    logger.info("Mercari US Monitor ready at http://%s:%s", settings.app_host, settings.app_port)

    try:
        yield
    finally:
        logger.info("Shutting down Mercari US Monitor...")
        await monitoring_service.stop()
        await notification_service.stop()
        await client.stop()
        await dispose_engine()
        logger.info("Shutdown complete.")


app = FastAPI(
    title="Mercari US Monitor",
    description="Local monitoring tool for Mercari US search results. Not affiliated with Mercari.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(ValidationError)
async def _validation_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(DuplicateKeywordError)
async def _duplicate_keyword_handler(request: Request, exc: DuplicateKeywordError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


app.include_router(api_router)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await handle_websocket(websocket)


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
else:

    @app.get("/")
    async def frontend_not_built() -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "Frontend is not built yet. Run `cd frontend && npm install && npm run build`, "
                    "then restart, or use `npm run dev` for a hot-reloading development server. "
                    "The API itself is live — see /docs."
                )
            },
        )
