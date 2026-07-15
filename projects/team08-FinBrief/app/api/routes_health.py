"""Health check endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.config import Settings, get_settings


router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str
    mock_data: bool


@router.get("/health", response_model=HealthResponse)
def get_health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="finbrief",
        version=settings.app_version,
        environment=settings.app_env,
        mock_data=settings.enable_mock_data,
    )
