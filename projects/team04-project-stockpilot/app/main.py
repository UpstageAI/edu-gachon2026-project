"""FastAPI 진입점 — 앱 생성, 미들웨어, 라우터 등록."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.api.routes import api_router
from app.graph.graph import get_stockpilot_graph
from app.repositories.disclosure import start_corporation_cache_warmup

# 프론트엔드 개발 서버 (Vite)
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작 시 그래프를 미리 컴파일해 첫 요청 지연을 없앤다."""
    logger.info("StockPilot API 시작")
    get_stockpilot_graph()
    start_corporation_cache_warmup()
    yield
    logger.info("StockPilot API 종료")


app = FastAPI(title="StockPilot API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")
