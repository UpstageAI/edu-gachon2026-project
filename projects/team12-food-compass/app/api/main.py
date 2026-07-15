from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.tracing import flush_traces

app = FastAPI(title="Food Compass API")
model = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("shutdown")
async def _flush_langfuse_on_shutdown() -> None:
    # Langfuse는 배치로 트레이스를 보내므로, 서버가 내려가기 전에 마저 전송 — 트레이싱이
    # 비활성(langfuse 미설치·키 미설정)이면 flush_traces()가 즉시 아무 일도 안 하고 반환됨.
    flush_traces()
