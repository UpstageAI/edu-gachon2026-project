"""
backend/main.py
FastAPI 앱 생성 + 라우터 등록만 담당한다(정문).
실제 로직은 routers/ 와 app/ 에 있다.
"""

import threading

from fastapi import FastAPI

from app.services.observability import setup_observability
from backend.routers import chat, health, recipe_image

app = FastAPI(title="Healthy Meal Agent API")

# LLMOps 관찰가능성: litellm 호출을 Langfuse로 트레이싱(키 없으면 자동 비활성화).
setup_observability()

app.include_router(health.router)
app.include_router(chat.router)
app.include_router(recipe_image.router)


def _warm_up() -> None:
    """LLM Router 연결을 미리 데운다(콜드 스타트 완화).

    서버 기동 직후 첫 사용자 요청은 LLM 연결 세팅 때문에 ~2초 더 걸린다.
    시작 시 가벼운 분류 호출을 한 번 돌려두면 그 비용을 미리 치러, 사용자 첫 요청이 빨라진다.
    실패해도 서비스에 영향 없도록 조용히 무시한다(관측만 안 될 뿐).
    """
    try:
        from app.services.intent_router import classify_intent_llm

        classify_intent_llm("추천")  # 결과는 버림 — 연결·모델 로딩 목적
    except Exception:  # noqa: BLE001
        pass


@app.on_event("startup")
def _on_startup() -> None:
    # 워밍업이 서버 기동을 막지 않도록 백그라운드 스레드에서 실행.
    threading.Thread(target=_warm_up, daemon=True).start()


@app.get("/")
def read_root() -> dict[str, str]:
    return {"message": "Healthy Meal Agent API is initialized."}
