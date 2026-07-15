"""API v1 router assembly."""

from fastapi import APIRouter

from app.api.routes_cards import router as cards_router
from app.api.routes_health import router as health_router
from app.api.routes_ingestion import router as ingestion_router
from app.api.routes_reports import router as reports_router
from app.api.routes_subscriptions import router as subscriptions_router


api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(subscriptions_router, tags=["subscriptions"])
api_router.include_router(ingestion_router, tags=["ingestion"])
api_router.include_router(reports_router, tags=["reports"])
api_router.include_router(cards_router, tags=["cards"])
