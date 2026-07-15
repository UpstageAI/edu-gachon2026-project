"""규정 문서를 임베딩해 Supabase documents 테이블에 적재한다.

app/rag/regulations.py의 REGULATIONS를 임베딩해서 저장한다.
실행: python -m app.rag.ingest
"""

import logging
import time
import urllib.request
from collections import deque
from typing import Any

from dotenv import load_dotenv

from app.clients.embedding import embed
from app.clients.http import post_json, read_json
from app.clients.supabase import (
    documents_table,
    supabase_headers,
    supabase_url,
    vector_literal,
)
from app.logging_config import setup_logging
from app.rag.regulations import REGULATIONS

logger = logging.getLogger(__name__)

EMBEDDING_RPM = 100
EMBEDDING_TPM = 300_000
# 정확히 0.6초보다 약간 여유를 둬 분당 100회 경계 오차를 피한다.
REQUEST_INTERVAL_SECONDS = 60 / EMBEDDING_RPM + 0.05
MAX_RATE_LIMIT_RETRIES = 5
SUPABASE_BATCH_SIZE = 10
MAX_STORAGE_RETRIES = 5


class EmbeddingRateLimiter:
    """임베딩 요청을 RPM/TPM 제한 안에서 순차 실행하도록 조절한다."""

    def __init__(self) -> None:
        self.last_request_at: float | None = None
        self.token_events: deque[tuple[float, int]] = deque()

    def wait(self, text: str) -> None:
        # 별도 tokenizer 없이 글자 수를 토큰 수로 간주해 보수적으로 계산한다.
        estimated_tokens = max(1, len(text))
        while True:
            now = time.monotonic()
            while self.token_events and now - self.token_events[0][0] >= 60:
                self.token_events.popleft()

            rpm_wait = 0.0
            if self.last_request_at is not None:
                rpm_wait = max(0.0, REQUEST_INTERVAL_SECONDS - (now - self.last_request_at))

            used_tokens = sum(tokens for _, tokens in self.token_events)
            tpm_wait = 0.0
            if used_tokens + estimated_tokens > EMBEDDING_TPM and self.token_events:
                tpm_wait = max(0.0, 60 - (now - self.token_events[0][0]) + 0.05)

            wait_seconds = max(rpm_wait, tpm_wait)
            if wait_seconds <= 0:
                now = time.monotonic()
                self.last_request_at = now
                self.token_events.append((now, estimated_tokens))
                return
            logger.info("임베딩 rate limit 대기: %.2f초", wait_seconds)
            time.sleep(wait_seconds)


def _embed_with_retry(text: str, limiter: EmbeddingRateLimiter) -> list[float]:
    """제한에 맞춰 임베딩하고 429/연결 실패는 백오프 후 재시도한다."""
    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        limiter.wait(text)
        try:
            return embed(text, "passage")
        except RuntimeError as exc:
            message = str(exc)
            is_rate_limit = "HTTP 429" in message
            is_connection_failure = "Connection failed:" in message
            if not (is_rate_limit or is_connection_failure) or attempt >= MAX_RATE_LIMIT_RETRIES:
                raise
            delay = min(60, 5 * (2**attempt))
            reason = "요청 제한(429)" if is_rate_limit else "네트워크 연결 실패"
            logger.warning(
                "임베딩 %s: %d/%d회 재시도 전 %d초 대기",
                reason,
                attempt + 1,
                MAX_RATE_LIMIT_RETRIES,
                delay,
            )
            time.sleep(delay)
    raise RuntimeError("embedding retry exhausted")


def build_regulation_rows(
    limiter: EmbeddingRateLimiter | None = None,
) -> list[dict[str, Any]]:
    """REGULATIONS를 임베딩해 저장용 row 목록으로 만든다."""
    limiter = limiter or EmbeddingRateLimiter()
    rows = []
    for regulation_id, text in REGULATIONS.items():
        text = text.strip()
        if not text:
            continue
        logger.info("제%s조 임베딩 중...", regulation_id)
        rows.append(
            {
                "content": text,
                "metadata": {"source": "regulation", "regulation_id": regulation_id},
                "embedding": vector_literal(_embed_with_retry(text, limiter)),
            }
        )
    return rows


def delete_all_documents() -> None:
    """documents 테이블을 전부 비운다."""
    request = urllib.request.Request(
        supabase_url(documents_table(), {"id": "not.is.null"}),
        headers=supabase_headers({"Prefer": "return=minimal"}),
        method="DELETE",
    )
    read_json(request)


def _store_document_batch(rows: list[dict[str, Any]]) -> None:
    """문서 배치를 저장한다. statement timeout이면 더 작은 배치로 분할한다."""
    if not rows:
        return

    for attempt in range(MAX_STORAGE_RETRIES + 1):
        try:
            post_json(
                supabase_url(documents_table()),
                supabase_headers({"Prefer": "return=minimal"}),
                rows,
            )
            return
        except RuntimeError as exc:
            message = str(exc)
            is_statement_timeout = '"code":"57014"' in message
            is_connection_failure = "Connection failed:" in message

            if is_statement_timeout and len(rows) > 1:
                midpoint = len(rows) // 2
                logger.warning(
                    "Supabase 저장 timeout: %d건을 %d건/%d건으로 분할",
                    len(rows),
                    midpoint,
                    len(rows) - midpoint,
                )
                _store_document_batch(rows[:midpoint])
                _store_document_batch(rows[midpoint:])
                return

            if not is_connection_failure or attempt >= MAX_STORAGE_RETRIES:
                raise

            delay = min(60, 5 * (2**attempt))
            logger.warning(
                "Supabase 연결 실패: %d/%d회 재시도 전 %d초 대기",
                attempt + 1,
                MAX_STORAGE_RETRIES,
                delay,
            )
            time.sleep(delay)


def store_documents(rows: list[dict[str, Any]]) -> None:
    """문서를 작은 배치로 나눠 Supabase에 저장한다."""
    total = len(rows)
    for start in range(0, total, SUPABASE_BATCH_SIZE):
        batch = rows[start : start + SUPABASE_BATCH_SIZE]
        _store_document_batch(batch)
        logger.info(
            "문서 저장 진행: %d/%d건",
            min(start + len(batch), total),
            total,
        )


def add_regulations() -> None:
    """기존 문서를 지우고 규정 전체를 새로 임베딩해 적재한다."""
    logger.info("총 %d개의 규정을 임베딩합니다.", len(REGULATIONS))
    rows = build_regulation_rows()

    logger.info("기존에 저장된 문서를 전부 삭제합니다...")
    delete_all_documents()

    logger.info("새로 임베딩한 규정 문서를 저장합니다...")
    store_documents(rows)
    logger.info("저장 완료: %d건", len(rows))


def main() -> int:
    load_dotenv()
    setup_logging()
    try:
        add_regulations()
    except RuntimeError as exc:
        logger.error("적재 실패: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
