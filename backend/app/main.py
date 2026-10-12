"""FastAPI application factory."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app import db as db_module
from app.api import admin, analytics, ask, auth, deadlines, documents, notifications, rules
from app.config import get_settings
from app.observability import RequestContextMiddleware, configure_logging
from app.services.jobs import Worker

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.auto_create_schema:
        db_module.init_db()
    worker: Worker | None = None
    if settings.worker_embedded and settings.env != "test":
        worker = Worker()
        worker.start_background()
    log.info("api started", extra={"extra_fields": {"llm_provider": settings.llm_provider, "env": settings.env}})
    yield
    if worker:
        worker.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.env == "prod" and (settings.jwt_secret.startswith("dev-only") or len(settings.jwt_secret) < 32):
        raise RuntimeError("Set DOCPILOT_JWT_SECRET to a random value of at least 32 characters in production")
    if settings.env != "test":
        configure_logging()
    app = FastAPI(
        title="DocPilot API",
        version="1.0.0",
        description="AI document intelligence: structured extraction, risk detection and cited Q&A.",
        lifespan=lifespan,
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-request-id"],
    )
    for r in (
        auth.router,
        documents.router,
        ask.router,
        analytics.router,
        deadlines.router,
        deadlines.calendar_router,
        rules.router,
        notifications.router,
        admin.router,
    ):
        app.include_router(r)

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict:
        """Liveness: the process is up."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"])
    def readyz() -> dict:
        """Readiness: the database is reachable."""
        with db_module.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready", "llm_provider": settings.llm_provider}

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
