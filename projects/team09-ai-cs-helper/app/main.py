import logging
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from app.clients.inquiry_logs import append_inquiry_log, list_inquiry_logs
from app.clients.supabase import (
    delete_inquiry,
    get_inquiry,
    list_inquiries,
    mark_inquiry_failed,
    update_final_answer,
)
from app.graph.graph import graph
from app.graph.nodes import start_inquiry
from app.graph.state import create_initial_state
from app.logging_config import setup_logging

# 로컬 실행 시 .env를 로드한다 (Supabase/LLM 자격증명 등).
load_dotenv()


setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="AI CS Helper", version="0.1.0")

# 데모용 CORS: 정적 프론트엔드(file:// 또는 localhost)에서의 호출을 허용한다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class InquiryRequest(BaseModel):
    text: str


class AnswerUpdate(BaseModel):
    final_answer: str


class LogActionRequest(BaseModel):
    event: str


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/inquiries")
def get_inquiries() -> list[dict]:
    """전체 문의 목록(최신순)을 반환한다."""
    logger.info("GET /inquiries")
    return list_inquiries()


@app.get("/inquiries/{inquiry_id}")
def read_inquiry(inquiry_id: str) -> dict:
    """단일 문의 상세를 반환한다."""
    logger.info("GET /inquiries/%s", inquiry_id)
    inquiry = get_inquiry(inquiry_id)
    if inquiry is None:
        logger.warning("GET /inquiries/%s -> 404", inquiry_id)
        raise HTTPException(status_code=404, detail="inquiry not found")
    return inquiry


@app.get("/inquiries/{inquiry_id}/logs")
def get_inquiry_logs(inquiry_id: str) -> list[dict]:
    """문의 한 건의 처리 로그를 실행 순서대로 반환한다."""
    logger.info("GET /inquiries/%s/logs", inquiry_id)
    if get_inquiry(inquiry_id) is None:
        raise HTTPException(status_code=404, detail="inquiry not found")
    return list_inquiry_logs(inquiry_id)


@app.post("/inquiries/{inquiry_id}/logs/actions")
def save_log_action(inquiry_id: str, payload: LogActionRequest) -> dict[str, str | bool]:
    """수정 시작/취소처럼 DB 변경이 없는 상담원 UI 행동을 기록한다."""
    actions = {
        "edit_started": ("상담원 답변 수정 시작", "상담원이 AI 답변 수정 모드에 진입했습니다."),
        "edit_cancelled": (
            "상담원 답변 수정 취소",
            "수정 내용을 취소하고 기존 AI 답변으로 돌아갔습니다.",
        ),
    }
    if payload.event not in actions:
        raise HTTPException(status_code=400, detail="unsupported log action")
    if get_inquiry(inquiry_id) is None:
        raise HTTPException(status_code=404, detail="inquiry not found")

    title, message = actions[payload.event]
    saved = append_inquiry_log(
        inquiry_id,
        stage="human",
        event=payload.event,
        title=title,
        message=message,
    )
    return {"event": payload.event, "saved": saved}


@app.patch("/inquiries/{inquiry_id}")
def save_final_answer(inquiry_id: str, payload: AnswerUpdate) -> dict:
    """관리자가 검토,작성한 최종 답변을 저장한다."""
    logger.info("PATCH /inquiries/%s (final_answer %d자)", inquiry_id, len(payload.final_answer))
    updated = update_final_answer(inquiry_id, payload.final_answer)
    if updated is None:
        logger.warning("PATCH /inquiries/%s -> 404", inquiry_id)
        raise HTTPException(status_code=404, detail="inquiry not found")
    return updated


@app.delete("/inquiries/{inquiry_id}")
def remove_inquiry(inquiry_id: str) -> dict[str, str]:
    """상담 내역 한 건을 영구 삭제한다."""
    logger.info("DELETE /inquiries/%s", inquiry_id)
    if not delete_inquiry(inquiry_id):
        logger.warning("DELETE /inquiries/%s -> 404", inquiry_id)
        raise HTTPException(status_code=404, detail="inquiry not found")
    return {"inquiry_id": inquiry_id, "status": "deleted"}


@app.post("/inquiries")
def create_inquiry(payload: InquiryRequest) -> dict[str, str]:
    """유저 문의를 받아 그래프를 실행한다. inquiry_id는 DB가 알아서 생성한다."""
    logger.info("POST /inquiries 수신 (문의 %d자)", len(payload.text))
    initial_state = create_initial_state(
        session_id=str(uuid.uuid4()),
        inquiry_id=None,
        messages=[HumanMessage(content=payload.text)],
    )

    # 1) 먼저 INSERT해서 inquiry_id를 확보한다. 여기서 실패하면 저장된 게 없으므로
    #    예외를 그대로 올려 500으로 응답한다(진짜 실패).
    inquiry_id = start_inquiry(initial_state)
    initial_state["inquiry_id"] = inquiry_id

    # 2) 파이프라인 실행. 중간에 회복 불가능한 오류가 나면 이미 접수된 문의를
    #    '상담원 확인 필요'로 마킹하고 부분 성공으로 응답한다(500 대신).
    logger.info("그래프 실행 시작 inquiry_id=%s", inquiry_id)
    try:
        result = graph.invoke(initial_state)
    except Exception as exc:
        logger.exception(
            "그래프 실행 중 예외 발생 -> 상담원 확인 필요로 이관: inquiry_id=%s", inquiry_id
        )
        append_inquiry_log(
            inquiry_id,
            stage="pipeline",
            event="failed",
            title="문의 처리 실패",
            message=str(exc),
            data={"error_type": type(exc).__name__, "error": str(exc)},
        )
        try:
            mark_inquiry_failed(inquiry_id)
        except Exception:
            logger.exception("실패 상태 마킹 실패: inquiry_id=%s", inquiry_id)
        return {
            "inquiry_id": inquiry_id,
            "session_id": initial_state["session_id"],
            "status": "상담원 확인 필요",
        }

    logger.info(
        "그래프 실행 종료: inquiry_id=%s intent=%s ai_answer=%s status=%s",
        result.get("inquiry_id"),
        result.get("intent"),
        "있음" if result.get("ai_answer") else "없음",
        result.get("status"),
    )
    return {"inquiry_id": inquiry_id, "session_id": result["session_id"]}
