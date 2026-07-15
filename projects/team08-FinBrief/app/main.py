"""FastAPI entrypoint for FinBrief."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or get_settings()

    app = FastAPI(
        title=runtime_settings.app_name,
        version=runtime_settings.app_version,
        description="FinBrief personalized AI financial briefing API",
    )

    def _settings_override() -> Settings:
        if settings is None:
            return runtime_settings
        current = Settings()
        return current.model_copy(
            update={
                "app_name": runtime_settings.app_name,
                "app_version": runtime_settings.app_version,
                "app_env": runtime_settings.app_env,
                "api_v1_prefix": runtime_settings.api_v1_prefix,
                "enable_mock_data": runtime_settings.enable_mock_data,
            }
        )

    app.dependency_overrides[get_settings] = _settings_override
    app.include_router(api_router, prefix=runtime_settings.api_v1_prefix)

    service_info = {
        "service": "finbrief",
        "health": f"{runtime_settings.api_v1_prefix}/health",
        "docs": "/docs",
    }

    @app.get("/status", include_in_schema=False)
    def status() -> dict[str, str]:
        return service_info

    # 랜딩 페이지(정적 프론트)를 루트에 서빙한다. frontend/ 디렉터리가 있으면
    # "/"에서 index.html을, "/assets/..."에서 정적 자산을 제공한다.
    # API(/api/v1/*)·문서(/docs)는 이 마운트보다 먼저 등록되어 우선 매칭된다.
    frontend_dir = Path(os.getenv("FINBRIEF_FRONTEND_DIR", "frontend"))
    if frontend_dir.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=frontend_dir, html=True),
            name="frontend",
        )
    else:

        @app.get("/", include_in_schema=False)
        def root() -> dict[str, str]:
            return service_info

    return app


app = create_app()
