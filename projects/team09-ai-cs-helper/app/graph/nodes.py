"""
LangGraph 노드 함수 모음.

마스킹 -> RAG검색 -> 라우터 -> 리뷰 -> DB저장 순서로 돌아감.
(최초 INSERT는 그래프 실행 전에 main.py가 start_inquiry로 먼저 수행해 inquiry_id를 확보한다.)
각 노드는 state를 받아서 '바뀐 부분만' dict로 return -> LangGraph가 알아서 합쳐줌.

[오류 처리 원칙]
- RAG/router/review는 외부 호출(LLM/임베딩) 실패 시 예외를 올리지 않고 '상담원 이관'으로
  우아하게 폴백한다(파이프라인 중단 방지).
- 그 외 노드(masking/save_to_db)의 예외는 그대로 올려 main.py가 한 곳에서 처리한다.
"""

import json
import logging
import time
from datetime import datetime, timezone

from app.clients import llm
from app.clients.inquiry_logs import append_inquiry_log
from app.clients.supabase import insert_inquiry, update_inquiry
from app.graph.prompts import (
    CATEGORIES,
    REVIEW_PROMPT_VERSION,
    REWRITE_PROMPT_VERSION,
    ROUTER_PROMPT_VERSION,
    build_review_prompt,
    build_rewrite_prompt,
    build_router_prompt,
)
from app.graph.state import InquiryState
from app.privacy.masking import mask_personal_info_with_details
from app.rag.search import search_with_usage

logger = logging.getLogger(__name__)


# 리뷰에서 fail 나면 다시 답변 만드는데, 무한루프 방지용으로 최대 3번까지만 재시도
MAX_RETRY = 3

# 처리 상태 값. AI 답변 초안이 있으면 승인 대기(STATUS_AI_DRAFTED),
# 없으면(이관·오류) 상담원이 직접 처리(STATUS_NEEDS_HUMAN)로 통일한다.
STATUS_AI_DRAFTED = "답변 생성"
STATUS_NEEDS_HUMAN = "상담원 확인 필요"


def _duration_ms(started_at: float) -> int:
    # 시작 시각(perf_counter 값) 받아서 지금까지 몇 ms 걸렸는지 계산해주는 함수
    return int((time.perf_counter() - started_at) * 1000)


def _human_handoff_update() -> dict:
    """오류/이관으로 AI 처리를 계속할 수 없을 때의 공통 상태(상담원 이관)."""
    return {
        "intent": "to_human",
        "ai_answer": None,
        "reviewer_type": "human",
        "status": STATUS_NEEDS_HUMAN,
    }


def _last_user_text(state: InquiryState) -> str:
    """고객이 마지막으로 보낸 문의 내용을 꺼낸다(제일 최근 메시지 = 맨 끝 [-1])."""
    if not state["messages"]:
        return ""  # 혹시 메시지가 하나도 없으면 빈 문자열
    return state["messages"][-1].content


def _query_text(state: InquiryState) -> str:
    """외부 서비스(RAG/LLM)에는 개인정보 마스킹된 문의만 넘긴다."""
    return state["masked_text"] or ""


def _parse_llm_json(raw: str) -> dict:
    """LLM 응답에서 JSON만 파싱한다. ```json 코드블록이 섞여 있어도 처리."""

    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")  # 앞뒤 ` 떼기
        if text.startswith("json"):
            text = text[4:]  # "json" 4글자 잘라내기
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        # LLM이 JSON이 아닌 응답을 준 경우 — 답변 생성 실패의 주요 원인. 원문을 남긴다.
        logger.error("LLM JSON 파싱 실패. 원문: %r", raw)
        raise


def _normalize_router_result(parsed: dict, valid_regulation_ids: set[int] | None = None) -> dict:
    """Router JSON의 허용값을 검증하고 안전한 상태로 정규화한다."""
    # intent(답변 주체)는 딱 두 개 중 하나여야 함. 이상한 값이면 아예 에러내서 중단.
    intent = parsed.get("intent")
    if intent not in {"AI_generate", "to_human"}:
        raise ValueError(f"invalid intent: {intent!r}")

    # 카테고리가 우리가 정해둔 목록에 없으면 그냥 "기타"로 처리
    category = parsed.get("categories")
    if category not in CATEGORIES:
        logger.warning("허용되지 않은 카테고리 %r -> 기타", category)
        category = "기타"

    # 답변 텍스트 앞뒤 공백 정리
    answer = parsed.get("ai_answer")
    if isinstance(answer, str):
        answer = answer.strip() or None

    # AI가 답변하겠다고 해놓고 답변이 비어있으면 사람한테 넘김
    if intent == "AI_generate" and answer is None:
        logger.warning("AI_generate 답변이 비어 있어 to_human으로 전환")
        intent = "to_human"
    if intent == "to_human":
        answer = None  # 사람이 답할 거면 AI 답변은 지움

    # 답변 근거로 쓴 규정 ID 목록. 리스트가 아니면 빈 리스트로.
    regulation_ids = parsed.get("used_regulation_ids")
    if not isinstance(regulation_ids, list):
        regulation_ids = []
    # 실제로 검색된 규정 ID만 남기기 (LLM이 없는 ID 지어내는 거 방지)
    if valid_regulation_ids is not None:
        regulation_ids = [rid for rid in regulation_ids if rid in valid_regulation_ids]

    return {
        "intent": intent,
        "categories": category,
        "ai_answer": answer,
        "evidence_found": bool(parsed.get("evidence_found")),  # LLM이 근거 찾았는지 여부
        # 사람한테 넘기는 경우엔 근거 ID 남길 필요 없어서 빈 리스트로
        "used_regulation_ids": regulation_ids if intent == "AI_generate" else [],
        "intent_reason": str(
            parsed.get("intent_reason") or ""
        ).strip(),  # 왜 이렇게 판단했는지 이유
    }


def _normalize_review_result(parsed: dict) -> dict:
    """Review JSON의 허용값과 feedback 규칙을 검증한다."""
    # 리뷰 결과도 pass/fail 두 개만 허용. 그 외엔 에러.
    result = parsed.get("answer_review")
    if result not in {"pass", "fail"}:
        raise ValueError(f"invalid answer_review: {result!r}")
    feedback = parsed.get("review_feedback")
    if result == "fail" and (not isinstance(feedback, str) or not feedback.strip()):
        feedback = "답변을 실질적으로 수정해야 하는 이유를 구체적으로 작성하지 못했습니다."
    return {"answer_review": result, "review_feedback": feedback}


def start_inquiry(state: InquiryState) -> str:
    """문의를 INSERT하고 시작 로그를 남긴 뒤 생성된 inquiry_id를 반환한다.

    그래프 실행 전에 호출해 id를 먼저 확보한다. 이렇게 하면 이후 파이프라인이 중간에
    실패해도 엔드포인트가 이 id로 '상담원 확인 필요' 처리(부분 성공)를 할 수 있다.
    """
    started = time.perf_counter()
    new_id = insert_inquiry(state)
    duration = _duration_ms(started)
    logger.info("start_inquiry: INSERT 완료 inquiry_id=%s", new_id)

    original = _last_user_text(state)  # 고객 문의 원문
    append_inquiry_log(
        new_id,
        stage="pipeline",
        event="started",
        title="문의 처리 파이프라인 시작",
        message="새로운 문의 처리를 시작합니다.",
        data={
            "inquiry_id": new_id,
            "session_id": state["session_id"],
            "started_at": datetime.fromtimestamp(
                state["pipeline_started_at"], timezone.utc
            ).isoformat(),
        },
    )
    append_inquiry_log(
        new_id,
        stage="inquiry",
        event="received",
        title="고객 문의 접수",
        message="고객 문의 원문을 접수했습니다.",
        data={"question": original, "question_length": len(original)},
    )
    append_inquiry_log(
        new_id,
        stage="database",
        event="insert_succeeded",
        title="문의 DB 저장 완료",
        message="inquiries 테이블에 문의를 저장했습니다.",
        duration_ms=duration,
        data={
            "operation": "INSERT",
            "table": "inquiries",
            "saved_fields": ["question", "status"],
            "status": state["status"],
        },
    )
    return new_id


def save_to_db_node(state: InquiryState) -> dict:
    """AI 처리 결과를 inquiries 테이블에 UPDATE하고 파이프라인 완료 로그를 남긴다.

    이 UPDATE를 끝으로 그래프는 종료된다(이후는 상담원 웹에서 최종 답변을 저장).
    """
    started = time.perf_counter()
    update_inquiry(state)
    duration = _duration_ms(started)
    logger.info(
        "save_to_db: UPDATE 완료 inquiry_id=%s status=%s", state["inquiry_id"], state["status"]
    )

    append_inquiry_log(
        state["inquiry_id"],
        stage="database",
        event="update_succeeded",
        title="AI 처리 결과 저장 완료",
        message="AI 처리 결과를 inquiries 테이블에 반영했습니다.",
        duration_ms=duration,
        data={
            "operation": "UPDATE",
            "table": "inquiries",
            "saved_fields": [
                "retrieved_docs",
                "categories",
                "ai_answer",
                "reviewer_type",
                "status",
            ],
            "categories": state["categories"],
            "status": state["status"],
            "ai_answer_exists": bool(state["ai_answer"]),
        },
    )
    append_inquiry_log(
        state["inquiry_id"],
        stage="pipeline",
        event="completed",
        title="AI 문의 처리 완료",
        message="상담원 검토 대기 상태로 전환되었습니다.",
        # 여기는 파이프라인 '시작~끝' 전체 시간이라 wall-clock인 time.time() 기준으로 계산
        duration_ms=int((time.time() - state["pipeline_started_at"]) * 1000),
        data={
            "category": state["categories"],
            "intent": state["intent"],
            "review": state["answer_review"],
            "retry_count": state["retry_count"],
            "status": state["status"],
            "waiting_for_human": True,
        },
    )
    return {}


def mask_personal_info_node(state: InquiryState) -> dict[str, str]:
    """원문은 유지하고 외부 서비스용 문의에서 개인정보를 마스킹한다."""

    original = _last_user_text(state)
    started = time.perf_counter()
    result = mask_personal_info_with_details(original)  # {"masked_text":..., "counts":...} 반환
    masked = result["masked_text"]
    logger.info("personal_info_mask: 마스킹 적용=%s", original != masked)  # 뭐라도 가려졌는지
    total_count = sum(result["counts"].values())  # 종류별 개수 다 더해서 총 몇 건 가렸는지
    append_inquiry_log(
        state["inquiry_id"],
        stage="masking",
        event="completed",
        title="개인정보 마스킹 완료",
        message=f"개인정보 {total_count}건을 마스킹했습니다.",
        duration_ms=_duration_ms(started),
        data={
            "original": original,
            "masked": masked,
            "total_count": total_count,
            "counts": result["counts"],  # {"이름": 1, "전화번호": 2, ...} 이런 식
        },
    )
    return {"masked_text": masked}


def rag_search_node(state: InquiryState) -> dict:
    """문의(마스킹본)로 규정 문서를 검색해 retrieved_docs를 채운다.

    임베딩/문서 조회 실패 시 예외를 올리지 않고 rag_failed 신호만 남긴다.
    -> 다음 router 노드가 이 신호를 보고 LLM 호출 없이 즉시 상담원에게 이관한다.
    """
    query_text = _query_text(state)
    started = time.perf_counter()
    try:
        results, embedding_result = search_with_usage(query_text, top_k=5)
    except Exception as exc:
        logger.exception("rag_search 실패 -> 상담원 이관")
        append_inquiry_log(
            state["inquiry_id"],
            stage="rag",
            event="search_failed",
            title="관련 규정 검색 실패",
            message="규정 검색 중 오류가 발생해 상담원에게 이관합니다.",
            duration_ms=_duration_ms(started),
            data={"query": query_text, "error_type": type(exc).__name__, "error": str(exc)},
        )
        return {"retrieved_docs": [], "rag_failed": True}

    docs = [
        {"content": doc.get("content", ""), "metadata": doc.get("metadata", {}), "score": score}
        for score, doc in results
    ]
    duration = _duration_ms(started)
    logger.info("rag_search: 문의=%r 검색결과=%d건", query_text[:80], len(docs))
    log_results = [
        {
            "rank": rank,
            "regulation_id": doc["metadata"].get("regulation_id"),
            "score": doc["score"],
            "content": doc["content"],
        }
        for rank, doc in enumerate(docs, start=1)  # 1등부터 번호 매기기
    ]
    append_inquiry_log(
        state["inquiry_id"],
        stage="rag",
        event="search_completed",
        title="관련 규정 검색 완료",
        message=f"관련 규정 {len(docs)}건을 검색했습니다.",
        duration_ms=duration,
        data={
            "query": query_text,
            "embedding_model": embedding_result.model,
            "token_usage": embedding_result.token_usage,
            "top_k": 5,
            "results": log_results,
        },
    )
    return {"retrieved_docs": docs}  # 다음 노드(라우터)가 씀


def _router_result_update(parsed: dict) -> dict:
    """Router 파싱 결과를 state 업데이트 dict로 변환한다."""
    ai_answer = parsed["ai_answer"]
    return {
        "intent": parsed["intent"],
        "categories": parsed["categories"],
        "ai_answer": ai_answer,
        # 답변 초안이 있으면 승인 대기, 없으면(이관) 상담원이 직접 처리.
        "reviewer_type": None if ai_answer else "human",
        "status": STATUS_AI_DRAFTED if ai_answer else STATUS_NEEDS_HUMAN,
    }


def _log_router_result(
    state: InquiryState,
    *,
    is_retry: bool,
    parsed: dict,
    llm_result: llm.LLMResult,
    prompt: str,
    prompt_version: str,
    raw: str,
    duration: int,
    previous_answer: str | None,
) -> None:
    """router 성공 처리 결과를 구조화 로그로 남긴다(로그 조립을 노드 본문과 분리)."""
    intent = parsed["intent"]
    ai_answer = parsed["ai_answer"]
    if is_retry:
        event, title = "answer_regenerated", "AI 답변 재생성"
        message = "검수 반려 사유를 반영해 답변을 다시 생성했습니다."
    else:
        event, title = "analysis_and_answer_completed", "AI 문의 분석 및 답변 생성"
        message = (
            "AI가 답변 가능한 문의로 판단했습니다."
            if intent == "AI_generate"
            else "상담원 답변이 필요한 문의로 판단했습니다."
        )
    append_inquiry_log(
        state["inquiry_id"],
        stage="router",
        event=event,
        title=title,
        message=message,
        attempt=state["retry_count"] + 1,
        duration_ms=duration,
        data={
            "model": llm_result.model,
            "prompt_version": prompt_version,
            "token_usage": llm_result.token_usage,
            "prompt": prompt,
            "raw_response": raw,
            "category": parsed["categories"],
            "intent": intent,
            "evidence_found": parsed["evidence_found"],
            "used_regulation_ids": parsed["used_regulation_ids"],
            "intent_reason": parsed["intent_reason"],
            "answer_available": bool(ai_answer),
            "answer": ai_answer,
            "previous_answer": previous_answer if is_retry else None,
            "feedback": state["review_feedback"] if is_retry else None,
            "next_node": "review" if intent == "AI_generate" else "final_save",
        },
    )


def router_node(state: InquiryState) -> dict:
    """
    ROUTER: 답변 가능/불가능 판단 + (가능 시) 답변 동시 생성.

    intent가 None이면 최초 호출(판단+생성), 이미 있으면 재시도 호출(답변만 재생성).
    """
    query_text = _query_text(state)

    # RAG 검색이 오류로 실패한 상태면 판단 근거가 없으므로 LLM 호출 없이 즉시 상담원 이관.
    if state.get("rag_failed"):
        logger.warning("router: RAG 검색 실패 상태 -> LLM 생략하고 상담원 이관")
        append_inquiry_log(
            state["inquiry_id"],
            stage="router",
            event="handoff_degraded",
            title="규정 검색 실패로 상담원 이관",
            message="관련 규정을 검색하지 못해 상담원에게 이관합니다.",
            attempt=state["retry_count"] + 1,
            data={"reason": "rag_failed"},
        )
        return _human_handoff_update()

    is_retry = state["intent"] is not None
    previous_answer = state["ai_answer"]  # 재시도면 이전 답변을 참고용으로 넘겨줌
    if is_retry:
        # 재시도: 반려 사유(review_feedback) 반영해서 답변만 새로 씀
        prompt = build_rewrite_prompt(
            query_text,
            state["retrieved_docs"],
            state["categories"],
            previous_answer,
            state["review_feedback"],
        )
        prompt_version = REWRITE_PROMPT_VERSION
    else:
        # 최초: 판단 + 답변 생성 둘 다
        prompt = build_router_prompt(query_text, state["retrieved_docs"])
        prompt_version = ROUTER_PROMPT_VERSION

    logger.info(
        "router: %s 호출",
        f"재시도(retry_count={state['retry_count']})" if is_retry else "최초",
    )
    started = time.perf_counter()
    try:
        llm_result = llm.ask_with_usage(prompt)  # 실제로 LLM 호출하는 부분
        raw = llm_result.content
        logger.debug("router: LLM 원문=%r", raw)
        # 방금 검색해온 규정들의 진짜 ID만 set으로 모아둠 (LLM이 없는 ID 지어내는 거 방지용)
        valid_regulation_ids = {
            doc.get("metadata", {}).get("regulation_id")
            for doc in state["retrieved_docs"]
            if isinstance(doc.get("metadata", {}).get("regulation_id"), int)
        }
        parsed = _normalize_router_result(_parse_llm_json(raw), valid_regulation_ids)
    except Exception as exc:
        # LLM 호출 실패/응답 형식 오류 등: 전체를 중단하지 말고 상담원 이관으로 폴백.
        logger.exception("router 처리 실패 -> 상담원 이관")
        append_inquiry_log(
            state["inquiry_id"],
            stage="router",
            event="handoff_degraded",
            title="AI 라우팅 실패로 상담원 이관",
            message="AI 분석·답변 생성 중 오류가 발생해 상담원에게 이관합니다.",
            attempt=state["retry_count"] + 1,
            duration_ms=_duration_ms(started),
            data={
                "prompt_version": prompt_version,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        return _human_handoff_update()

    duration = _duration_ms(started)
    ai_answer = parsed["ai_answer"]
    logger.info(
        "router: intent=%s categories=%s ai_answer=%s",
        parsed["intent"],
        parsed["categories"],
        "생성됨(%d자)" % len(ai_answer) if ai_answer else "없음(null)",
    )
    _log_router_result(
        state,
        is_retry=is_retry,
        parsed=parsed,
        llm_result=llm_result,
        prompt=prompt,
        prompt_version=prompt_version,
        raw=raw,
        duration=duration,
        previous_answer=previous_answer,
    )
    return _router_result_update(parsed)


def review_node(state: InquiryState) -> dict:
    """ROUTER: 평가 및 재시도. ai_answer의 타당성을 검증한다.

    검수 LLM 실패/형식 오류 시 생성된 답변을 폐기하고 상담원 이관으로 폴백한다.
    """
    query_text = _query_text(state)
    prompt = build_review_prompt(query_text, state["retrieved_docs"], state["ai_answer"])

    started = time.perf_counter()
    try:
        llm_result = llm.ask_with_usage(prompt)
        raw = llm_result.content
        logger.debug("review: LLM 원문=%r", raw)
        parsed = _normalize_review_result(_parse_llm_json(raw))
    except Exception as exc:
        # retry_count를 MAX로 올려 route_after_review가 재시도 없이 final_save로 가게 한다.
        logger.exception("review 처리 실패 -> AI 답변 폐기하고 상담원 이관")
        append_inquiry_log(
            state["inquiry_id"],
            stage="review",
            event="handoff_degraded",
            title="AI 검수 실패로 상담원 이관",
            message="검수 처리 중 오류가 발생해 상담원이 직접 검토합니다.",
            attempt=state["retry_count"] + 1,
            duration_ms=_duration_ms(started),
            data={
                "prompt_version": REVIEW_PROMPT_VERSION,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        return {
            **_human_handoff_update(),
            "answer_review": "fail",
            "review_feedback": "검수 처리 중 오류가 발생해 상담원이 직접 검토합니다.",
            "retry_count": MAX_RETRY,
        }

    duration = _duration_ms(started)
    review_result = parsed["answer_review"]
    updates: dict = {
        "answer_review": review_result,
        "review_feedback": parsed["review_feedback"],
    }
    if review_result == "fail":
        updates["retry_count"] = state["retry_count"] + 1
        logger.info(
            "review: FAIL (retry_count %d -> %d, MAX=%d) 사유=%r",
            state["retry_count"],
            updates["retry_count"],
            MAX_RETRY,
            parsed["review_feedback"],
        )
    else:
        logger.info("review: PASS")

    resulting_retry_count = updates.get("retry_count", state["retry_count"])
    next_node = (
        "final_save" if review_result == "pass" or resulting_retry_count >= MAX_RETRY else "router"
    )

    # fail인데 재시도 여력까지 소진 -> 검수 미통과본을 버리고 상담원에게 이관.
    if review_result == "fail" and resulting_retry_count >= MAX_RETRY:
        logger.warning("review: 최대 재시도 도달 -> AI 답변 폐기하고 상담원 이관")
        updates.update({"ai_answer": None, "reviewer_type": "human", "status": STATUS_NEEDS_HUMAN})

    message = (
        "생성된 답변이 문의와 관련 규정에 부합합니다."
        if review_result == "pass"
        else parsed["review_feedback"]  # 반려면 그 사유를 메시지로
    )
    append_inquiry_log(
        state["inquiry_id"],
        stage="review",
        event="review_passed" if review_result == "pass" else "review_failed",
        title="AI 답변 검수 통과" if review_result == "pass" else "AI 답변 검수 반려",
        message=message,
        attempt=state["retry_count"] + 1,
        duration_ms=duration,
        data={
            "model": llm_result.model,
            "prompt_version": REVIEW_PROMPT_VERSION,
            "token_usage": llm_result.token_usage,
            "prompt": prompt,
            "raw_response": raw,
            "answer": state["ai_answer"],
            "review": review_result,
            "feedback": parsed["review_feedback"],
            "retry_count": resulting_retry_count,
            "max_retry": MAX_RETRY,
            "regulations": [doc["content"] for doc in state["retrieved_docs"]],
            "next_node": next_node,
        },
    )

    return updates
