"""라우터 취합 — /api/v1 하위에 등록."""
from fastapi import APIRouter

from app.api.routes import auth, chat, conversations, health, watchlist

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(chat.router, prefix="/chat", tags=["Chat"])
api_router.include_router(conversations.router, prefix="/conversations", tags=["Conversations"])
api_router.include_router(health.router, prefix="/health", tags=["Health"])
api_router.include_router(watchlist.router, prefix="/watchlist", tags=["Watchlist"])
