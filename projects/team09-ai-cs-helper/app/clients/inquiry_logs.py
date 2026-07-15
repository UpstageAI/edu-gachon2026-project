"""문의 처리 과정의 구조화 로그를 Supabase에 저장하고 조회한다."""

import json
import logging
import os
import urllib.request
from typing import Any

from app.clients.http import read_json
from app.clients.supabase import supabase_headers, supabase_url

logger = logging.getLogger(__name__)


def inquiry_logs_table() -> str:
    """문의 처리 로그 테이블 이름을 반환한다."""
    return os.getenv("SUPABASE_INQUIRY_LOGS_TABLE", "inquiry_logs").strip() or "inquiry_logs"


def append_inquiry_log(
    inquiry_id: str | None,
    *,
    stage: str,
    event: str,
    title: str,
    message: str | None = None,
    attempt: int | None = None,
    duration_ms: int | None = None,
    data: dict[str, Any] | None = None,
) -> bool:
    """처리 로그를 저장한다. 실패해도 본 파이프라인은 중단하지 않는다."""
    if not inquiry_id:
        return False

    values: dict[str, Any] = {
        "inquiry_id": inquiry_id,
        "stage": stage,
        "event": event,
        "title": title,
        "data": data or {},
    }
    if message is not None:
        values["message"] = message
    if attempt is not None:
        values["attempt"] = attempt
    if duration_ms is not None:
        values["duration_ms"] = duration_ms

    try:
        request = urllib.request.Request(
            supabase_url(inquiry_logs_table()),
            data=json.dumps(values, ensure_ascii=False).encode("utf-8"),
            headers=supabase_headers({"Prefer": "return=minimal"}),
            method="POST",
        )
        read_json(request)
    except Exception:
        logger.exception(
            "문의 처리 로그 저장 실패: inquiry_id=%s stage=%s event=%s",
            inquiry_id,
            stage,
            event,
        )
        return False

    logger.info(
        "문의 처리 로그 저장: inquiry_id=%s stage=%s event=%s",
        inquiry_id,
        stage,
        event,
    )
    return True


def list_inquiry_logs(inquiry_id: str) -> list[dict[str, Any]]:
    """문의 한 건의 처리 로그를 실행 순서대로 조회한다."""
    request = urllib.request.Request(
        supabase_url(
            inquiry_logs_table(),
            {
                "inquiry_id": f"eq.{inquiry_id}",
                "select": "*",
                "order": "sequence.asc",
            },
        ),
        headers=supabase_headers(),
        method="GET",
    )
    rows = read_json(request) or []
    logger.info("문의 처리 로그 조회: inquiry_id=%s %d건", inquiry_id, len(rows))
    return rows
