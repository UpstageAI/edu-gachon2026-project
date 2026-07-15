"""
LangGraph 노드 함수들.
respond 노드는 SSE 스트리밍이라 여기 포함하지 않고 app/main.py에서 직접
llm_client.build_respond_prompt + stream_response로 처리함.
(그래프는 parse -> route -> stats/retrieve -> gate 까지만 실행하고,
 gate 결과를 보고 main.py가 스트리밍 respond 또는 escalate 메시지를 흘려보냄)
"""
import sys
import os
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.graph.state import AgentState
from app.llm_client import parse_user_query, judge_relevance
from tools.stats_tool import get_disaster_stats
from tools.retrieve_tool import retrieve_guidelines
from tools.resilience import ToolUnavailableError
from preprocessors.disaster_type_phone_map import get_contact

logger = logging.getLogger("app.graph.nodes")

# 1차 게이트 임계값: 검색된 행동요령 중 가장 가까운 거리가 이보다 크면
# "관련 근거 없음"으로 판단 (코사인 거리, 작을수록 유사)
RELEVANCE_THRESHOLD = 0.6


def parse_node(state: AgentState) -> dict:
    """
    체크포인터가 연결되어 있으면, 이 노드가 실행되기 전 `state`에는 같은
    thread_id의 '이전 턴' 값들이 이미 복원되어 들어와 있음 (user_query만
    이번 호출에서 새로 덮어써짐). 이번 턴에서 못 뽑은 필드는 이전 값을
    그대로 이어받아서, "그럼 노약자는 뭘 더 챙겨야 해?" 같은 맥락 의존적인
    후속 질문도 지역/시기 정보 없이 자연스럽게 처리되게 함.
    (체크포인터 없이 호출되면 state에 이전 값이 없어서 그냥 None -> 문제없이 폴백)
    """
    parsed = parse_user_query(state["user_query"])

    region_sido = parsed.get("region_sido") or state.get("region_sido")
    region_sigungu = parsed.get("region_sigungu") or state.get("region_sigungu")
    month = parsed.get("month") or state.get("month")
    disaster_type = parsed.get("disaster_type") or state.get("disaster_type")
    # has_vulnerable은 한 번 언급되면 대화 내내 유효하다고 보고 OR로 유지
    has_vulnerable = bool(parsed.get("has_vulnerable")) or bool(state.get("has_vulnerable"))

    return {
        "region_sido": region_sido,
        "region_sigungu": region_sigungu,
        "month": month,
        "intent": parsed.get("intent"),  # intent는 후속 질문마다 새로 판단 (다른 의도일 수 있음)
        "disaster_type": disaster_type,
        "has_vulnerable": has_vulnerable,
        "parse_failed": bool(parsed.get("_parse_failed", False)),
    }


def route_after_parse(state: AgentState) -> str:
    """
    조건부 라우팅.
    - prevention: 통계 집계에 지역+월이 반드시 필요하므로 둘 다 있어야 진행
    - reactive: disaster_type을 못 뽑아도 무작정 재질문하지 않음. 원본 질문 자체가
      이미 구체적인 상황 설명(예: "붕괴 징후가 보입니다")을 담고 있는 경우가 많아서,
      파싱이 완벽하지 않아도 벡터 검색이 원문으로 커버할 수 있음
      (retrieve_node의 폴백 경로 참고). intent가 reactive로만 판단됐으면 진행.
    """
    if state.get("parse_failed"):
        return "parse_failed"

    intent = state.get("intent")

    if intent == "prevention":
        if not state.get("region_sido") or not state.get("month"):
            return "parse_failed"
        return "stats_and_retrieve"

    if intent == "reactive":
        return "stats_and_retrieve"

    return "parse_failed"


def stats_node(state: AgentState) -> dict:
    """예방형(prevention) 질문에서만 실행. 지역x월별 통계 집계."""
    if state.get("intent") != "prevention":
        return {"stats_result": None}

    result = get_disaster_stats(
        sido=state["region_sido"],
        sigungu=state.get("region_sigungu"),
        month=state["month"],
    )
    return {"stats_result": result}


def retrieve_node(state: AgentState) -> dict:
    """
    예방형: stats에서 나온 상위 재난유형 '각각에 대해 개별로' 행동요령 검색
            (한 문장으로 합쳐서 검색하지 않음 - 유형별 매칭 정확도를 위해)
            "기타"는 실제 행동요령 카테고리가 없는 잡다한 안전공지 묶음이라
            검색 대상에서 제외 (재난문자 취합 요약에는 그대로 남겨둠)
    반응형: 사용자가 언급한 disaster_type으로 직접 검색.
            disaster_type을 못 뽑았어도(파싱이 완벽하지 않을 수 있음) 재질문으로
            바로 안 보내고, 원본 질문 그대로 벡터 검색하는 폴백 경로(맨 아래 else)를 씀
            - 원본 문장 자체가 이미 구체적 상황 설명을 담고 있어 검색에 충분한 경우가 많음.

    임베딩 API/DB가 재시도까지 다 실패하면(ToolUnavailableError) 빈 리스트로
    우아하게 강등함. gate_node가 "검색결과 없음" -> distance=999(기본값)로 처리해서
    자동으로 에스컬레이션되므로, 별도 예외처리 로직을 여기서 새로 안 만들어도 됨.
    """
    try:
        return _retrieve_node_inner(state)
    except ToolUnavailableError as e:
        logger.warning(f"retrieve_node 도구 호출 실패, 빈 결과로 강등 처리: {e}")
        return {"retrieved_guidelines": []}


def _retrieve_node_inner(state: AgentState) -> dict:
    intent = state.get("intent")
    has_vulnerable = state.get("has_vulnerable", False)
    vulnerable_note = " 노약자 동반 시 주의사항 포함" if has_vulnerable else ""

    if intent == "reactive" and state.get("disaster_type"):
        query = f"{state['disaster_type']} 발생 시 행동요령{vulnerable_note}"
        results = retrieve_guidelines(query, top_k=5)
        for r in results:
            r["matched_disaster_type"] = state["disaster_type"]
        return {"retrieved_guidelines": results}

    if intent == "prevention":
        stats_result = state.get("stats_result")
        stats_top_types = []
        if stats_result and stats_result.breakdown:
            stats_top_types = [
                b["disaster_type"] for b in stats_result.breakdown
                if b["disaster_type"] != "기타"
            ][:3]

        # 사용자가 질문에 명시적으로 언급한 재난유형은, 통계 상위 3개에 안 들어도
        # 우선적으로 검색 대상에 포함 (사용자가 직접 물어본 걸 무시하면 안 됨)
        explicit_type = state.get("disaster_type")
        top_types = []
        if explicit_type:
            top_types.append(explicit_type)
        for t in stats_top_types:
            if t not in top_types:
                top_types.append(t)
        top_types = top_types[:4]  # 명시 유형 1개 + 통계 상위 최대 3개

        if not top_types:
            # 통계에 유의미한 재난유형이 없으면(전부 기타 등) 지역 기반 일반 안전정보로 폴백
            query = f"{state.get('region_sido', '')} 여행 안전 주의사항{vulnerable_note}"
            results = retrieve_guidelines(query, top_k=5)
            for r in results:
                r["matched_disaster_type"] = None
            return {"retrieved_guidelines": results}

        # 재난유형별로 각각 검색해서 결과를 합침 (유형마다 top_k=3)
        # has_vulnerable이면 쿼리에 "노약자 동반" 명시 -> 각 재난유형 행동요령 안에
        # 섞여있는 노약자 특화 문구(예: "부모님 약물 복용 여부 확인")가 더 잘 검색되게 함
        all_results = []
        for dtype in top_types:
            query = f"{dtype} 발생 시 행동요령 및 대비{vulnerable_note}"
            per_type_results = retrieve_guidelines(query, top_k=3)
            for r in per_type_results:
                r["matched_disaster_type"] = dtype
            all_results.extend(per_type_results)

        all_results.sort(key=lambda r: r["distance"])
        return {"retrieved_guidelines": all_results}

    query = state["user_query"]
    results = retrieve_guidelines(query, top_k=5)
    for r in results:
        r["matched_disaster_type"] = None
    return {"retrieved_guidelines": results}


def gate_node(state: AgentState) -> dict:
    """
    1차 게이트 (관련도 임계값 기준).
    - retrieve 결과 중 가장 가까운 거리가 임계값보다 크면 -> 에스컬레이션
    - stats도 완전히 표본부족(insufficient)이고 retrieve도 부실하면 -> 에스컬레이션
    2차 게이트(LLM 적합성 판정)는 추후 추가.
    """
    guidelines = state.get("retrieved_guidelines") or []
    stats_result = state.get("stats_result")

    best_distance = min((g["distance"] for g in guidelines), default=999)
    stats_insufficient = (
        stats_result is not None and stats_result.scope_used == "insufficient"
    )

    if best_distance > RELEVANCE_THRESHOLD:
        return {
            "should_escalate": True,
            "escalate_reason": f"검색된 행동요령의 관련도가 낮음 (distance={best_distance:.3f})",
        }

    if state.get("intent") == "prevention" and stats_insufficient and best_distance > RELEVANCE_THRESHOLD * 0.7:
        return {
            "should_escalate": True,
            "escalate_reason": "통계 표본 부족 + 관련 행동요령 근거 부족",
        }

    return {"should_escalate": False, "escalate_reason": None}


def judge_node(state: AgentState) -> dict:
    """
    2차 게이트 (LLM 적합성 판정).
    1차 게이트(코사인 거리 임계값)가 이미 에스컬레이션으로 결정했으면 LLM 호출 없이 스킵
    (비용 절감 - 1차에서 걸러진 건 2차까지 갈 필요 없음).
    1차를 통과한 것 중에서, 검색된 문서가 "주제는 비슷하지만 질문의 정확한 요구사항을
    실제로 충족하지 못하는" 경계선 케이스를 추가로 걸러냄.
    """
    if state.get("should_escalate"):
        return {}

    guidelines = state.get("retrieved_guidelines") or []
    if not guidelines:
        return {}

    verdict = judge_relevance(state["user_query"], guidelines)

    if not verdict.get("sufficient", True):
        return {
            "should_escalate": True,
            "escalate_reason": f"2차 판정(LLM): {verdict.get('reason', '질문에 대한 충분한 근거 부족')}",
        }

    return {}


def escalate_node(state: AgentState) -> dict:
    """에스컬레이션: 재난유형별 공식 연락처 안내"""
    disaster_type = state.get("disaster_type")
    if not disaster_type:
        stats_result = state.get("stats_result")
        if stats_result and stats_result.breakdown:
            disaster_type = stats_result.breakdown[0]["disaster_type"]

    contact = get_contact(disaster_type or "기타")
    return {"escalate_contact": contact}