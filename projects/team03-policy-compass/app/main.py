from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import chat, health
from app.core.config import get_settings
from app.core.observability import get_langfuse_client, shutdown_langfuse

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    logger = logging.getLogger("app")
    settings = get_settings()
    logger.info("%s 시작 (env=%s)", settings.app_name, settings.app_env)
    get_langfuse_client()
    yield
    shutdown_langfuse()
    logger.info("%s 종료", settings.app_name)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        # Wildcard origins and credentialed requests must not be combined.
        # The current frontend uses bearerless JSON/SSE requests, so local
        # wildcard mode does not need cross-origin cookies.
        allow_credentials="*" not in settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def root() -> FileResponse:
        return FileResponse(str(STATIC_DIR / "index.html"))

    @app.get("/health")
    async def legacy_health() -> dict[str, str]:
        return {"status": "ok", "service": "policy-compass"}

    return app


app = create_app()
