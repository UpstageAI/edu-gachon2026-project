from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.core.observability import flush_langfuse


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    finally:
        flush_langfuse()


def create_app() -> FastAPI:
    app = FastAPI(
        title="LawHelp API",
        description="Mock-based Day2 생활법령 Agent backend",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(chat_router)
    return app


app = create_app()
