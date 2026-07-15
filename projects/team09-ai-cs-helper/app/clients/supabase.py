"""Supabase REST 접근 클라이언트.

documents 테이블에 임베딩 문서를 저장/조회.
"""

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from typing import Any

from app.clients.http import env, read_json

logger = logging.getLogger(__name__)


def supabase_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Supabase REST 요청 헤더를 만든다."""
    key = env("SUPABASE_KEY")
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if extra:
        headers.update(extra)
    return headers


def supabase_url(path: str, query: dict[str, str] | None = None) -> str:
    """Supabase REST URL을 만든다."""
    base_url = env("SUPABASE_URL").rstrip("/")
    query_string = urllib.parse.urlencode(query or {})
    suffix = f"?{query_string}" if query_string else ""
    return f"{base_url}/rest/v1/{path}{suffix}"


def documents_table() -> str:
    """문서 테이블 이름을 반환한다."""
    return os.getenv("SUPABASE_DOCUMENTS_TABLE", "documents").strip() or "documents"


def vector_literal(values: list[float]) -> str:
    """리스트를 리터럴 문자열로 변환한다."""
    return "[" + ",".join(str(value) for value in values) + "]"


def parse_embedding(value: Any) -> list[float]:
    """DB에서 읽은 embedding을 float 리스트로 변환한다."""
    if isinstance(value, str):
        value = json.loads(value)
    return [float(item) for item in value]


def fetch_documents() -> list[dict[str, Any]]:
    """documents 테이블의 전체 문서를 가져온다."""
    request = urllib.request.Request(
        supabase_url(documents_table(), {"select": "id,content,metadata,embedding"}),
        headers=supabase_headers(),
        method="GET",
    )
    return read_json(request) or []


def inquiries_table() -> str:
    """문의 테이블 이름을 반환한다."""
    return os.getenv("SUPABASE_INQUIRIES_TABLE", "inquiries").strip() or "inquiries"


def _serialize_inquiry_state(state: dict) -> dict:
    """InquiryState에서 DB 컬럼에 맞는 값만 뽑아 dict로 만든다.

    session_id, intent, answer_review, review_feedback, retry_count는
    그래프 실행 중에만 쓰는 값이라 DB에 저장하지 않는다.
    """
    question = state["messages"][0].content if state["messages"] else None
    values = {
        "question": question,
        "retrieved_docs": state["retrieved_docs"],
        "categories": state["categories"],
        "ai_answer": state["ai_answer"],
        "final_answer": state["final_answer"],
        "status": state["status"],
        "reviewer_type": state["reviewer_type"],
    }
    return {k: v for k, v in values.items() if v is not None}


def insert_inquiry(state: dict) -> str:
    """최초 저장. INSERT 하고 DB가 생성한 inquiry_id를 반환한다."""
    values = _serialize_inquiry_state(state)
    request = urllib.request.Request(
        supabase_url(inquiries_table()),
        data=json.dumps(values, ensure_ascii=False).encode("utf-8"),
        headers=supabase_headers({"Prefer": "return=representation"}),
        method="POST",
    )
    # INSERT는 멱등하지 않으므로 재시도를 끈다(응답 유실 시 중복 문의 방지).
    result = read_json(request, retries=1)
    new_id = result[0]["inquiry_id"]
    logger.info("inquiries INSERT: inquiry_id=%s", new_id)
    return new_id


# 시스템이 하는 업데이트는 여기서 끝. 직원용 웹에서 수정/승인 해서 버튼 누르면
# DB가 진짜 마지막으로 수정되고 문의 처리가 끝남.
def update_inquiry(state: dict) -> None:
    """마지막 저장. inquiry_id를 기준으로 UPDATE. 이 업데이트를 끝으로 그래프는 종료됨"""
    values = _serialize_inquiry_state(state)
    request = urllib.request.Request(
        supabase_url(inquiries_table(), {"inquiry_id": f"eq.{state['inquiry_id']}"}),
        data=json.dumps(values, ensure_ascii=False).encode("utf-8"),
        headers=supabase_headers({"Prefer": "return=minimal"}),
        method="PATCH",
    )
    read_json(request)
    logger.info("inquiries UPDATE: inquiry_id=%s", state["inquiry_id"])


def mark_inquiry_failed(inquiry_id: str, status: str = "상담원 확인 필요") -> None:
    """파이프라인 중 오류로 중단된 문의를 상담원 확인 필요 상태로 마킹한다(보상 트랜잭션).

    INSERT는 됐지만 이후 노드가 실패해 '문의 접수'에서 멈춘 좀비 행을 방지한다.
    PATCH는 멱등하므로 재시도해도 안전하다.
    """
    values = {"status": status, "reviewer_type": "human"}
    request = urllib.request.Request(
        supabase_url(inquiries_table(), {"inquiry_id": f"eq.{inquiry_id}"}),
        data=json.dumps(values, ensure_ascii=False).encode("utf-8"),
        headers=supabase_headers({"Prefer": "return=minimal"}),
        method="PATCH",
    )
    read_json(request)
    logger.info("문의 실패 마킹: inquiry_id=%s status=%s", inquiry_id, status)


# ---------------------------------------------------------------------------
# 관리자 페이지에서 쓰는 조회/수정 함수
# ---------------------------------------------------------------------------


def list_inquiries() -> list[dict[str, Any]]:
    """전체 문의를 최신순으로 가져온다."""
    request = urllib.request.Request(
        supabase_url(inquiries_table(), {"select": "*", "order": "created_at.desc"}),
        headers=supabase_headers(),
        method="GET",
    )
    rows = read_json(request) or []
    logger.info("inquiries 목록 조회: %d건", len(rows))
    return rows


def get_inquiry(inquiry_id: str) -> dict[str, Any] | None:
    """단일 문의를 조회한다. 없으면 None."""
    request = urllib.request.Request(
        supabase_url(inquiries_table(), {"inquiry_id": f"eq.{inquiry_id}", "select": "*"}),
        headers=supabase_headers(),
        method="GET",
    )
    rows = read_json(request) or []
    logger.info("inquiries 단건 조회: inquiry_id=%s 존재=%s", inquiry_id, bool(rows))
    return rows[0] if rows else None


def update_final_answer(
    inquiry_id: str,
    final_answer: str,
    status: str = "답변 완료",
) -> dict[str, Any] | None:
    """관리자가 검토, 작성한 최종 답변을 저장한다.

    AI 답변을 그대로 승인하면 답변자를 ai로, 수정하거나 AI 답변이 없으면
    human으로 판정하고 상태를 완료로 갱신한다.
    갱신된 행을 반환한다(없으면 None).
    """
    started = time.perf_counter()
    inquiry = get_inquiry(inquiry_id)
    if inquiry is None:
        return None

    ai_answer = str(inquiry.get("ai_answer") or "").strip()
    saved_answer = final_answer.strip()
    reviewer_type = "ai" if ai_answer and saved_answer == ai_answer else "human"
    values = {
        "final_answer": saved_answer,
        "reviewer_type": reviewer_type,
        "status": status,
    }
    request = urllib.request.Request(
        supabase_url(inquiries_table(), {"inquiry_id": f"eq.{inquiry_id}"}),
        data=json.dumps(values, ensure_ascii=False).encode("utf-8"),
        headers=supabase_headers({"Prefer": "return=representation"}),
        method="PATCH",
    )
    rows = read_json(request) or []
    logger.info("최종 답변 저장: inquiry_id=%s 성공=%s", inquiry_id, bool(rows))
    if rows:
        from app.clients.inquiry_logs import append_inquiry_log

        if reviewer_type == "ai":
            event = "answer_approved"
            title = "AI 답변 승인"
            message = "상담원이 AI 답변을 최종 답변으로 승인했습니다."
        elif ai_answer:
            event = "answer_modified"
            title = "수정 답변 등록"
            message = "상담원이 AI 답변을 수정해 최종 답변으로 등록했습니다."
        else:
            event = "answer_written"
            title = "상담원 답변 등록"
            message = "상담원이 답변을 직접 작성해 등록했습니다."

        duration_ms = int((time.perf_counter() - started) * 1000)
        append_inquiry_log(
            inquiry_id,
            stage="human",
            event=event,
            title=title,
            message=message,
            duration_ms=duration_ms,
            data={
                "ai_answer": ai_answer or None,
                "final_answer": saved_answer,
                "same_as_ai_answer": reviewer_type == "ai",
                "reviewer_type": reviewer_type,
                "status": status,
            },
        )
        append_inquiry_log(
            inquiry_id,
            stage="result",
            event="completed",
            title="문의 답변 처리 완료",
            message="최종 답변 등록이 완료되었습니다.",
            data={
                "ai_answer": ai_answer or None,
                "final_answer": saved_answer,
                "same_as_ai_answer": reviewer_type == "ai",
                "reviewer_type": reviewer_type,
                "status": status,
            },
        )
    return rows[0] if rows else None


def delete_inquiry(inquiry_id: str) -> bool:
    """문의 한 건을 삭제한다. 삭제된 행이 없으면 False를 반환한다."""
    request = urllib.request.Request(
        supabase_url(inquiries_table(), {"inquiry_id": f"eq.{inquiry_id}"}),
        headers=supabase_headers({"Prefer": "return=representation"}),
        method="DELETE",
    )
    rows = read_json(request) or []
    deleted = bool(rows)
    logger.info("문의 삭제: inquiry_id=%s 성공=%s", inquiry_id, deleted)
    return deleted
