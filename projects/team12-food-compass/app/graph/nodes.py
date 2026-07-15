from __future__ import annotations

import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm import invoke_with_fallback
from app.prompts.prompts import (
    ANSWER_GENERATION_SYSTEM_PROMPT,
    ANSWER_MONTH_DIFF_SUFFIX,
    ANSWER_NO_DATA,
    ANSWER_PRICE_LINE,
    ANSWER_PRICE_WITH_AMOUNT_AS_OF_LINE,
    ANSWER_PRICE_WITH_AMOUNT_LINE,
    ANSWER_PROCESSED_UNSUPPORTED_LINE,
    ANSWER_SUBSTITUTE_LINE,
    ANSWER_UNSUPPORTED_LINE,
    COMMON_ANSWER_SYSTEM_PROMPT,
    COMPARISON_ANSWER_SYSTEM_PROMPT,
    KNOWLEDGE_GENERATION_SYSTEM_PROMPT,
    KNOWLEDGE_NOT_FOUND,
    KNOWLEDGE_STUB_RESPONSE,
    OFFTOPIC_RESPONSE,
    PROCESSED_PRICE_ANSWER_SYSTEM_PROMPT,
)
from app.tools.item_alias import resolve_processed_alias
from app.tools.judge import parse_price  # noqa
from app.tools.kamis import LIVESTOCK_ITEMS
from app.tools.normalize import rice_price_per_bowl
from app.tools.price_gokr_snapshot import get_processed_price, search_processed_items
from app.tools.vector_store import get_collection, get_knowledge_collection

from .state import AgentState

_UNSUPPORTED_STATUS = "미지원"
# 비쌈 판정 시에만 hybrid 경로에서 대체품 검색으로 분기 (judge_price 결과 기준)
_EXPENSIVE_STATUS = "비쌈"
_N_SUBSTITUTES = 3


# [2026-07-14 추가] 프롬프트로 "마크다운 서식 금지"를 지시해도 LLM이 가끔 **굵게** 같은
# 마크다운 강조 문법을 흘리는 경우가 있어(실제로 가공식품 답변에서 관측됨), 프롬프트 지시만으론
# 보장이 안 돼서 코드에서 직접 제거 — 채팅 UI가 마크다운을 렌더링하지 않아 "**"이 그대로
# 노출되는 문제를 막기 위한 하드 개런티.
_MARKDOWN_EMPHASIS_RE = re.compile(r"\*\*|__")

# [2026-07-15 추가] "삼겹살"만 입력했을 때 LLM이 최종 답변 대신 "사용자가 삼겹살 가격을
# 물어봤고... 이모지는 2개 이하로 제한합니다..."처럼 시스템 프롬프트 지시사항을 그대로
# 되풀이하는 추론 과정/작성 계획을 답변으로 반환한 걸 실제로 확인함. 기존 하드개런티
# (품목명 언급 체크)는 이런 유출 텍스트 안에도 실제 상품명이 포함돼 있어 통과시켜버림 —
# 별도 탐지 필요.
#
# [2026-07-15 코드리뷰 반영] "사용자가"는 그 자체로는 정상 답변에도 등장할 여지가 있는
# 일반적인 단어라 단독으로는 오탐 위험이 있음(예: 정상 답변이 "사용자가 궁금해하실 만한
# 정보는~" 식으로 시작할 가능성을 완전히 배제 못함) — "이모지는"/"라고 나와 있습니다"처럼
# 정상 답변에 나올 일이 거의 없는 강한 마커는 그 자체로 판정하고, "사용자가"는 작성
# 계획/지시사항을 서술하는 표현과 함께 나올 때만 유출로 판단하도록 분리.
#
# [2026-07-15 (5) 추가] 특정 문구 몇 개만 마커로 등록하는 방식은 새로운 유출 표현이
# 나올 때마다 계속 마커를 추가해야 하는 두더지잡기라, "입력 프롬프트가 그대로 노출되는"
# 사고가 계속 재발함(실제 사용자 재현 보고) — app/prompts/prompts.py에 실제로 존재하는
# 구조적 표지(대괄호 섹션 제목, 노드별 프롬프트 공통 문구, 에이전트 자기소개 문장)를
# 추가해 프롬프트 "구조" 자체가 새어나온 경우까지 넓게 잡는다. 이 표지들은 정상적인
# 자연어 답변에서 나올 이유가 사실상 없어 강한 마커로 취급.
_PROMPT_STRUCTURE_LEAK_MARKERS = (
    "[데이터 무결성", "이 노드만의 규칙", "장바구니 물가 판단 에이전트입니다",
)
_STRONG_REASONING_LEAK_MARKERS = (
    "이모지는", "라고 나와 있습니다", "라고 나와있습니다",
    *_PROMPT_STRUCTURE_LEAK_MARKERS,
)
_WEAK_REASONING_LEAK_MARKER = "사용자가"
_PLAN_LANGUAGE_MARKERS = ("하면 됩니다", "작성합니다", "생략하고", "제한합니다", "언급할 것", "지어내지")


class _ReasoningLeakError(RuntimeError):
    """LLM이 최종 답변 대신 추론/작성 계획을 그대로 반환한 것으로 보일 때 발생."""


def _looks_like_leaked_reasoning(text: str) -> bool:
    if any(marker in text for marker in _STRONG_REASONING_LEAK_MARKERS):
        return True
    return _WEAK_REASONING_LEAK_MARKER in text and any(p in text for p in _PLAN_LANGUAGE_MARKERS)


# [2026-07-15 (7) 추가] Langfuse 트레이스에서 "... Potato Potato Potato Potato ..."처럼
# 같은 단어를 수십 번 반복하며 생성이 망가지는 사고를 실제로 확인함 — LLM 디코딩이
# 퇴화된 반복 루프에 빠지는 흔한 실패 모드로, 이게 응답 길이를 비정상적으로 늘려
# 프론트엔드의 httpx 타임아웃(ReadTimeout)까지 유발한 것으로 보임. app/core/llm.py의
# max_tokens/frequency_penalty로 발생 확률 자체를 낮췄지만, 그래도 새어나온 경우를
# 최종적으로 잡기 위한 코드 레벨 하드 개런티.
_MAX_CONSECUTIVE_WORD_REPEATS = 4


class _DegenerateOutputError(RuntimeError):
    """LLM이 같은 단어를 반복 생성하는 등 출력이 퇴화된 것으로 보일 때 발생."""


def _looks_like_degenerate_repetition(text: str) -> bool:
    words = text.split()
    run_length = 1
    for prev, curr in zip(words, words[1:], strict=False):
        if curr == prev:
            run_length += 1
            if run_length > _MAX_CONSECUTIVE_WORD_REPEATS:
                return True
        else:
            run_length = 1
    return False


def _invoke_with_prompts(specific_prompt: str, context: str) -> str:
    """공통 프롬프트(COMMON_ANSWER_SYSTEM_PROMPT) + 노드별 프롬프트를 각각 별도의
    SystemMessage로 함께 전달 — 페르소나·어투·이모지 개수 등 공통 원칙은 한 곳에서만
    관리하고, 노드별 프롬프트에는 그 노드만의 고유 규칙만 남기기 위함(2026-07-14 프롬프트 세분화).
    주 모델 실패 시 백업 모델로 폴백(app/core/llm.py). 반환 전 마크다운 강조 문법(**, __)을
    제거해 순수 텍스트만 남긴다.

    추론 유출이 감지되면 예외를 던진다 — 이 함수를 감싸는 4개 호출부(search_knowledge_node,
    _generate_processed_price_answer, _generate_comparison_answer, generate_answer_node)가
    이미 전부 "LLM 호출 실패 시 템플릿 답변으로 폴백"하는 try/except를 갖고 있어, 각 노드를
    따로 고칠 필요 없이 여기 한 곳에서만 방어하면 기존 폴백 경로를 그대로 재사용할 수 있음.
    """
    response = invoke_with_fallback(
        [
            SystemMessage(content=COMMON_ANSWER_SYSTEM_PROMPT),
            SystemMessage(content=specific_prompt),
            HumanMessage(content=context),
        ]
    )
    content = response.content
    text = content if isinstance(content, str) else str(content)
    text = _MARKDOWN_EMPHASIS_RE.sub("", text)
    if _looks_like_leaked_reasoning(text):
        # [2026-07-15 코드리뷰 반영] 예외 메시지 자체에 LLM 응답 원문을 그대로 담지
        # 않음(로그·트레이싱 시스템에 원치 않게 전체 내용이 노출될 수 있음) — 디버깅용
        # 원문은 별도로 콘솔에만 출력하고, 예외는 짧고 고정된 메시지만 사용.
        print(f"[nodes] LLM 응답이 추론 유출로 보여 폐기: {text!r}")
        raise _ReasoningLeakError("LLM이 최종 답변 대신 추론 과정을 반환한 것으로 보임")
    if _looks_like_degenerate_repetition(text):
        print(f"[nodes] LLM 응답이 반복 생성으로 퇴화된 것으로 보여 폐기: {text!r}")
        raise _DegenerateOutputError("LLM이 같은 단어를 반복 생성한 것으로 보임")
    return text


_KNOWLEDGE_N_RESULTS = 4

# 라우터가 추출하는 흔한 표현 -> 지식 DB item_name. 부분일치로도 안 잡히는 동의어만
# 최소한으로 매핑(예: 사용자는 "키위"라 부르지만 KAMIS/지식 DB는 "참다래"). 필요 시 추가.
_KNOWLEDGE_SYNONYMS = {"키위": "참다래"}


def _match_knowledge_item_names(collection: Any, items: list[str]) -> list[str]:
    """라우터가 추출한 품목명이 지식 DB의 item_name과 정확히 일치하지 않을 때를 위한
    부분일치 매칭. 예: 라우터가 "대파"/"애호박"/"돼지고기"로 추출해도 지식 DB의
    "파"/"호박"/"돼지" 문서에 매칭되도록(kamis 가격 경로의 ILIKE 폴백과 같은 취지).

    정확 일치가 먼저 시도된 뒤에만 쓰이므로, 짧은 이름(예: "파")이 다른 품목명에
    잘못 걸리는 위험은 실제로는 낮음("파프리카"는 정확 일치가 이미 잡음)."""
    got = collection.get(include=["metadatas"])
    known_names = {m["item_name"] for m in (got.get("metadatas") or [])}
    matched: list[str] = []
    for name in known_names:
        if any(name in it or it in name for it in items):
            matched.append(name)
    return matched


def _retrieve_knowledge_docs(user_query: str, items: list[str]) -> list[str]:
    """food_knowledge 컬렉션에서 질문 관련 지식 문서를 검색해 문서 텍스트 리스트로 반환.

    - 품목이 추출됐으면 그 품목명(item_name)으로 메타데이터 필터링해 해당 품목 문서만
      가져온다(결정론적, 다른 품목 문서가 섞이지 않음). 정확 일치가 없으면 부분일치로
      한 번 더 시도하고, 그래도 없으면 빈 리스트 → 호출부가 "정보 없음"으로 안내
      (LLM 자체 지식으로 지어내지 않음).
    - 품목이 없으면(일반 질문) 질문 텍스트로 의미 검색해 상위 문서를 가져온다.
    """
    collection = get_knowledge_collection()

    # 동의어("키위"->"참다래" 등)를 지식 DB 표기로 확장해 검색 대상에 포함
    items = list(dict.fromkeys(items + [_KNOWLEDGE_SYNONYMS[it] for it in items if it in _KNOWLEDGE_SYNONYMS]))

    if items:
        got = collection.get(
            where={"item_name": {"$in": items}},
            include=["documents"],
        )
        docs = list(got.get("documents") or [])
        if docs:
            return docs
        matched = _match_knowledge_item_names(collection, items)
        if matched:
            got = collection.get(
                where={"item_name": {"$in": matched}},
                include=["documents"],
            )
            return list(got.get("documents") or [])
        return []

    res = collection.query(
        query_texts=[user_query],
        n_results=_KNOWLEDGE_N_RESULTS,
        include=["documents"],
    )
    docs = res.get("documents") or [[]]
    return list(docs[0]) if docs else []


def search_knowledge_node(state: AgentState) -> dict[str, Any]:
    """제철·보관법 등 가격과 무관한 지식 질문에 대해, ChromaDB(food_knowledge)에서
    검색한 문서 내용만 근거로 답변을 생성한다(LLM 자체 지식으로 지어내지 않음)."""
    items = state.get("items", [])
    item = items[0] if items else "해당 품목"
    user_query = state.get("user_query", "")

    try:
        docs = _retrieve_knowledge_docs(user_query, items)
    except Exception as e:
        # 컬렉션 미적재(insertion_knowledge_rag.py 미실행) 등 — 지어내지 않고 준비 중 안내
        print(f"[search_knowledge] 지식 컬렉션 조회 실패: {e!r}")
        return {"knowledge_result": KNOWLEDGE_STUB_RESPONSE.format(item=item)}

    if not docs:
        return {"knowledge_result": KNOWLEDGE_NOT_FOUND.format(item=item)}

    facts = "\n".join(f"- {doc}" for doc in docs)
    context = f"사용자 질문: {user_query}\n참고 문서:\n{facts}"

    try:
        answer = _invoke_with_prompts(KNOWLEDGE_GENERATION_SYSTEM_PROMPT, context)
        return {"knowledge_result": answer}
    except Exception:
        return {"knowledge_result": KNOWLEDGE_STUB_RESPONSE.format(item=item)}


def _substitute_query_name(item_name: str) -> str:
    """축산물은 "돼지 갈비"처럼 "품목 부위" 합성 이름으로 판정되는데, 이 이름 그대로
    대체품을 검색하면 기존 자기 자신 제외 로직(완전 일치 검사)이 "돼지 갈비" != "돼지"라
    못 걸러내서 대체품 후보에 "돼지" 자기 자신이 나오는 문제가 있었음(2026-07-15 확인) —
    합성 이름이면 기본 품목명만 뽑아 검색하고, 그러면 기존 완전 일치 제외 로직이 정상 동작함."""
    first_token = item_name.split(" ", 1)[0]
    return first_token if first_token in LIVESTOCK_ITEMS else item_name


def _lookup_item_category(collection: Any, query: str) -> str | None:
    """대체품 컬렉션에서 해당 품목의 부류(category) 메타데이터를 조회. 없으면 None."""
    try:
        got = collection.get(where={"name": query}, include=["metadatas"])
    except Exception:
        return None
    metas = got.get("metadatas") or []
    return metas[0].get("category") if metas else None


def search_substitute_node(state: AgentState) -> dict[str, Any]:
    """비쌈으로 판정된 품목에 대해 ChromaDB에서 같은 부류(축산물/채소류 등) 안에서만
    유사한 품목 3개를 검색한다. [2026-07-15] 부류 필터를 걸기 전에는 "소"의 대체품으로
    천일염·새우젓 같은 다른 부류가 섞여 나왔음 — 같은 부류로 한정해 진짜 유사한 원물만
    나오도록 함."""
    judgments = state.get("judgment", [])
    expensive_items = [
        j["item_name"] for j in judgments if j.get("status") == _EXPENSIVE_STATUS
    ]

    if not expensive_items:
        return {"substitutes": []}

    query = _substitute_query_name(expensive_items[0])  # 비쌈 품목 중 첫 번째 기준으로 검색

    try:
        collection = get_collection()
    except Exception:
        return {"substitutes": []}

    # 비쌈 품목의 부류를 찾아 같은 부류 안에서만 검색. 부류를 못 찾으면(컬렉션에 없는
    # 품목 등) 대체품을 억지로 추천하지 않고 빈 리스트 반환(다른 부류 오염 방지).
    category = _lookup_item_category(collection, query)
    if category is None:
        return {"substitutes": []}

    # 자기 자신이 걸러질 걸 대비해 여유 있게 가져온다
    results = collection.query(
        query_texts=[query],
        n_results=_N_SUBSTITUTES + 5,
        where={"category": category},
        include=["documents", "metadatas"],
    )

    substitutes: list[str] = []
    for document, meta in zip(
        results["documents"][0],
        results["metadatas"][0],
        strict=True,
    ):
        original_name = (meta or {}).get("name")
        name = original_name or document

        # 검색어 자기 자신(설명이든 원래 이름이든)과 완전히 일치하면 제외
        if document == query or original_name == query:
            continue
        if name in substitutes:
            continue

        substitutes.append(name)
        if len(substitutes) >= _N_SUBSTITUTES:
            break
    return {"substitutes": substitutes}


def resolve_processed_items_node(state: AgentState) -> dict[str, Any]:
    """[시나리오 1: 쌀 vs 즉석밥] KAMIS에 없는 품목이 원물+가공식품 2개 조합의
    가공식품 쪽으로 보이면 참가격(price_gokr)으로 재조회.

    "이 품목이 원물인지 가공식품인지"를 LLM에게 분류시키지 않고, 이미 있는
    found 플래그(KAMIS 조회 결과)만으로 판별 — 정확히 "품목 2개, 하나는 KAMIS에서
    찾음 + 다른 하나는 못 찾음" 조합일 때만 참가격 폴백을 시도한다(스코프 제한:
    참가격 단독 조회나 3개 이상 품목 조합은 이번 시나리오 1 구현 범위 밖).
    """
    price_data = state.get("price_data", [])
    if len(price_data) != 2:
        return {}

    found_items = [item for item in price_data if item.get("found")]
    not_found_items = [item for item in price_data if not item.get("found")]
    if len(found_items) != 1 or len(not_found_items) != 1:
        return {}

    target = not_found_items[0]
    good_name = resolve_processed_alias(target["item_name"])
    if not good_name:
        return {}

    try:
        processed = get_processed_price(good_name, region=state.get("region"))
    except Exception as e:
        print(f"[resolve_processed_items] 참가격 DB 조회 실패: {e}")
        return {}
    if not processed:
        return {}

    updated_price_data = []
    for item in price_data:
        if item is target:
            updated_price_data.append(
                {
                    "item_name": item["item_name"],
                    "unit": "1공기(210g)",
                    "found": True,
                    "source": "price_gokr",
                    "avg_price": processed["avg_price"],
                    "sample_count": processed["sample_count"],
                    "inspect_day": processed["inspect_day"],
                    "region": processed.get("region"),
                }
            )
        else:
            updated_price_data.append({**item, "source": "kamis"})
    return {"price_data": updated_price_data}


def compare_items_node(state: AgentState) -> dict[str, Any]:
    """[시나리오 1] 원물(쌀) 밥 1공기 환산가와 가공식품(즉석밥) 1개(1공기) 평균가를
    비교해서 어느 쪽이 더 경제적인지 계산 — 판정(judge_price)이 아니라 두 품목 간
    비교라서 별도 로직으로 처리."""
    price_data = state.get("price_data", [])
    kamis_item = next((i for i in price_data if i.get("source") == "kamis"), None)
    gokr_item = next((i for i in price_data if i.get("source") == "price_gokr"), None)
    if kamis_item is None or gokr_item is None:
        return {"comparison": None}

    raw_price = parse_price(kamis_item.get("dpr1", "-"))
    raw_per_bowl = (
        rice_price_per_bowl(raw_price, kamis_item.get("unit")) if raw_price is not None else None
    )
    processed_per_bowl = gokr_item.get("avg_price")

    if raw_per_bowl is None or processed_per_bowl is None:
        return {"comparison": None}

    cheaper_item = kamis_item["item_name"] if raw_per_bowl < processed_per_bowl else gokr_item["item_name"]
    lower, higher = sorted([raw_per_bowl, processed_per_bowl])
    diff_pct = round((higher - lower) / higher * 100, 1)
    ratio = round(higher / lower, 1)

    return {
        "comparison": {
            "raw_item": kamis_item["item_name"],
            "raw_price_per_bowl": raw_per_bowl,
            "raw_price_as_of": kamis_item.get("price_as_of"),
            "processed_item": gokr_item["item_name"],
            "processed_price_per_bowl": processed_per_bowl,
            "cheaper_item": cheaper_item,
            "diff_pct": diff_pct,
            "ratio": ratio,
        }
    }


def search_processed_price_node(state: AgentState) -> dict[str, Any]:
    """[가공식품 단독 조회] KAMIS에 없는 품목(예: "참치캔")을 참가격(price_gokr)에서
    부분일치로 검색해 매칭되는 상품 전부의 평균가를 조회 — 비쌈/적정 판정은 하지 않음.

    ChromaDB 유사도 검색으로 상품 1개만 콕 집는 방식도 검토했으나, "소"를 검색했을 때
    "천일염"이 나왔던 것처럼 엉뚱한 상품이 잘못 골라질 위험이 있어(2026-07-14 사용자 확인)
    매칭되는 상품을 전부 보여주는 방식을 택함 — 잘못된 단일 매칭 자체가 발생할 수 없음.

    [2026-07-15 추가] 프론트에서 선택한 지역(state["region"])이 있으면 그 지역 평균을
    우선 사용(get_processed_price가 price_gokr_regional_avg 조회) — 사용자가 "전국
    평균과 경기도 평균이 다른데 왜 전국 평균만 나오냐"고 확인한 걸 계기로 연결.
    """
    price_data = state.get("price_data", [])
    region = state.get("region")
    results = []
    for item in price_data:
        matches = search_processed_items(item["item_name"])
        products = []
        for match in matches:
            price_info = get_processed_price(match["good_name"], region=region)
            if price_info:
                products.append(
                    {
                        "good_name": match["good_name"],
                        "avg_price": price_info["avg_price"],
                        "sample_count": price_info["sample_count"],
                        "region": price_info.get("region"),
                    }
                )
        results.append(
            {
                "item_name": item["item_name"],
                "found": bool(products),
                "products": products,
            }
        )
    return {"processed_prices": results}


def _processed_price_facts(results: list[dict]) -> str:
    """가공식품 단독 조회 답변 생성 LLM에게 넘겨줄 근거 데이터 — 이 안에 없는 수치는 지어내면 안 됨.

    [2026-07-15 추가] p["region"]이 있으면(프론트에서 지역을 선택한 경우) 그 지역
    평균이라는 걸 데이터 단계부터 명시 — 사용자가 "전국 평균과 경기도 평균이 다른데
    왜 전국 평균만 나오냐"고 확인한 걸 계기로, 이제는 지역 평균을 쓰면서도 마치
    전국 평균인 것처럼 말하지 않도록 LLM에게 시점(price_as_of)과 동일한 방식으로 투명하게 전달.
    """
    lines = []
    for r in results:
        if not r["found"]:
            lines.append(f"- {r['item_name']}: 가격 데이터 없음(지원하지 않는 품목 — 가격을 지어내지 말 것)")
            continue
        lines.append(f"- {r['item_name']} 검색 결과 (판정 없이 평균가만 제공):")
        for p in r["products"]:
            region = p.get("region")
            scope = f"{region} 매장" if region else "전국 매장"
            lines.append(f"  - {p['good_name']}: 평균 {p['avg_price']}원 ({scope} {p['sample_count']}곳 기준)")
    return "\n".join(lines)


def _template_processed_price_answer(results: list[dict]) -> str:
    """가공식품 단독 조회 LLM 호출 실패 시 사용하는 고정 템플릿."""
    lines = []
    for r in results:
        if not r["found"]:
            lines.append(ANSWER_PROCESSED_UNSUPPORTED_LINE.format(item=r["item_name"]))
            continue
        product_lines = ", ".join(
            f"{p['good_name']} {p.get('region') or '전국'} 평균 {p['avg_price']}원" for p in r["products"]
        )
        lines.append(f"{r['item_name']}: {product_lines}")
    return "\n".join(lines)


def _product_core_name(good_name: str) -> str:
    """"동원참치 라이트스탠다드(150g)" -> "동원참치 라이트스탠다드" — 괄호 안 규격 표기를 뗀 핵심명.

    LLM이 답변을 자연스럽게 쓰면서 "(150g)" -> "150g"처럼 괄호를 없애거나 띄어쓰기를
    살짝 바꾸는 경우가 흔해서(실제로 관측함), 전체 상품명을 그대로 문자열 대조하면
    정상 답변인데도 불필요하게 폴백되는 문제가 있어 핵심명만 비교.
    """
    return re.sub(r"\(.*\)\s*$", "", good_name).strip()


def _processed_price_answer_covers_results(answer: str, results: list[dict]) -> bool:
    """답변이 실제 조회 결과를 반영하고 있는지 확인.

    [2026-07-14 확인] r["item_name"]은 사용자가 부른 원문 그대로(예: "참치캔")라, LLM이
    매칭된 실제 상품명(예: "동원참치 라이트스탠다드")으로 자연스럽게 답하면 원문 "참치캔"이
    답변에 안 남는 경우가 많음 — 이건 정상 답변인데 원문 문자열만 확인하면 불필요하게
    폴백되므로, "찾음" 케이스는 매칭된 상품명(핵심명 기준) 중 하나라도 있는지로,
    "못 찾음" 케이스만 item_name으로 확인.
    """
    for r in results:
        if r["found"]:
            if any(_product_core_name(p["good_name"]) in answer for p in r["products"]):
                return True
        elif r["item_name"] in answer:
            return True
    return False


def _processed_price_answer_covers_regions(answer: str, results: list[dict]) -> bool:
    """[2026-07-15 추가] 지역 평균(예: "경기도")이 쓰였는데 답변이 그 지역명을 전혀
    언급하지 않으면(전국 평균인 것처럼 오해될 수 있음) 실패 처리 — 지역 데이터가 아예
    없는 경우(전국 평균만 쓰인 경우)엔 이 검증 자체를 건너뜀."""
    regions = {p.get("region") for r in results for p in r.get("products", []) if p.get("region")}
    if not regions:
        return True
    return any(region in answer for region in regions)


def _generate_processed_price_answer(results: list[dict], user_query: str) -> str:
    context = f"사용자 질문: {user_query}\n가공식품 가격 조회 결과:\n{_processed_price_facts(results)}"
    try:
        answer = _invoke_with_prompts(PROCESSED_PRICE_ANSWER_SYSTEM_PROMPT, context)
        if not _processed_price_answer_covers_results(answer, results):
            print(f"[generate_answer_node] 가공식품 답변에 조회 결과 누락, 템플릿 답변으로 폴백: {answer!r}")
            answer = _template_processed_price_answer(results)
        elif not _processed_price_answer_covers_regions(answer, results):
            print(f"[generate_answer_node] 가공식품 답변에 지역 표기 누락, 템플릿 답변으로 폴백: {answer!r}")
            answer = _template_processed_price_answer(results)
    except Exception as e:
        print(f"[generate_answer_node] 가공식품 LLM 호출 실패, 템플릿 답변으로 폴백: {e!r}")
        answer = _template_processed_price_answer(results)
    return answer


def _comparison_facts(comparison: dict) -> str:
    """비교형 답변 생성 LLM에게 넘겨줄 근거 데이터 — 이 안에 없는 수치는 지어내면 안 됨."""
    raw_as_of = comparison.get("raw_price_as_of")
    as_of_note = f"({raw_as_of} 기준)" if raw_as_of not in (None, "당일") else ""
    return (
        f"- {comparison['raw_item']}{as_of_note}: 밥 1공기(마른 쌀 90g = 지어진 밥 210g 기준)당 "
        f"약 {comparison['raw_price_per_bowl']}원\n"
        f"- {comparison['processed_item']}: 1개(1공기, 210g)당 약 {comparison['processed_price_per_bowl']}원\n"
        f"- 결론: {comparison['cheaper_item']}이(가) 약 {comparison['diff_pct']}%"
        f"({comparison['ratio']}배) 더 저렴함\n"
        "- 환산 기준(반드시 답변에 한 문장으로 그대로 밝힐 것): "
        "마른 쌀 90g = 지어진 밥 210g = 밥 1공기 = 즉석밥 1개"
    )


def _template_comparison_answer(comparison: dict) -> str:
    """비교형 답변 LLM 호출 실패 시 사용하는 고정 템플릿."""
    return (
        f"{comparison['raw_item']} 밥 1공기(마른 쌀 90g→지어진 밥 210g 기준)는 약 "
        f"{comparison['raw_price_per_bowl']}원, {comparison['processed_item']} 1개(1공기)는 약 "
        f"{comparison['processed_price_per_bowl']}원이에요. "
        f"{comparison['cheaper_item']} 쪽이 약 {comparison['diff_pct']}%({comparison['ratio']}배) 더 저렴해요."
    )


def _generate_comparison_answer(comparison: dict, user_query: str) -> str:
    context = f"사용자 질문: {user_query}\n비교 데이터:\n{_comparison_facts(comparison)}"
    try:
        answer = _invoke_with_prompts(COMPARISON_ANSWER_SYSTEM_PROMPT, context)
        if comparison["raw_item"] not in answer or comparison["processed_item"] not in answer:
            print(f"[generate_answer_node] 비교형 답변에 품목명 누락, 템플릿 답변으로 폴백: {answer!r}")
            answer = _template_comparison_answer(comparison)
    except Exception as e:
        print(f"[generate_answer_node] 비교형 LLM 호출 실패, 템플릿 답변으로 폴백: {e!r}")
        answer = _template_comparison_answer(comparison)
    return answer


def _template_answer(judgments: list[dict], substitutes: list[str]) -> str:
    """LLM 호출 실패 시 사용하는 고정 템플릿 답변."""
    lines = []
    for j in judgments:
        if j["status"] == _UNSUPPORTED_STATUS:
            lines.append(ANSWER_UNSUPPORTED_LINE.format(item=j["item_name"]))
            continue
        sign = "+" if j["diff_pct"] >= 0 else ""
        today_price = j.get("today_price")
        if today_price is not None:
            price_as_of = j.get("price_as_of")
            # [2026-07-14 추가] _price_facts()와 동일한 이유로, fallback 값을 쓴 경우
            # "N일 전 기준" 문구가 붙은 별도 템플릿 사용
            if price_as_of not in (None, "당일"):
                line = ANSWER_PRICE_WITH_AMOUNT_AS_OF_LINE.format(
                    item=j["item_name"], as_of=price_as_of, price=j["today_price"], unit=j.get("unit", "-"),
                    sign=sign, diff=j["diff_pct"], status=j["status"],
                )
            else:
                line = ANSWER_PRICE_WITH_AMOUNT_LINE.format(
                    item=j["item_name"], price=j["today_price"], unit=j.get("unit", "-"),
                    sign=sign, diff=j["diff_pct"], status=j["status"],
                )
        else:
            line = ANSWER_PRICE_LINE.format(item=j["item_name"], sign=sign, diff=j["diff_pct"], status=j["status"])
        month_diff = j.get("month_diff_pct")
        if month_diff is not None:
            line += ANSWER_MONTH_DIFF_SUFFIX.format(sign="+" if month_diff >= 0 else "", diff=month_diff)
        lines.append(line)
    if substitutes:
        lines.append(ANSWER_SUBSTITUTE_LINE.format(substitutes=", ".join(substitutes)))
    return "\n".join(lines)


# [2026-07-14 추가] "오이 지금 비싸?"를 실제로 5번 호출해보니 status="쌈"(저렴함)인데도
# 5번 중 4번이 "지금은 조금 비싼 편이에요!"로 시작하는 걸 확인함 — 프롬프트로 "판정 결과를
# 그대로 따르라"고 지시해도 시작 문장 선택 자체를 LLM의 자유 판단에 맡겨두면 diff_pct의
# 부호를 잘못 해석하는 등으로 실제 판정과 정반대로 답할 위험이 큼(재현 확률 80%로 확인).
# status는 이미 코드에서 확정된 값이라 LLM이 다시 판단할 이유가 없으므로, 시작 문장을
# 코드에서 직접 골라 "반드시 이 문장 그대로 시작할 것"으로 강제하고(아래 _select_opening_line),
# 그래도 어길 경우를 대비해 _opening_conflicts_with_status()로 한 번 더 검증한다.
_STATUS_OPENING_LINES = {
    "비쌈": "지금은 조금 비싼 편이에요!",
    "적정": "요즘 가격은 무난한 편이에요.",
    "쌈": "요즘 가격이 괜찮네요!!",
}
_EXPENSIVE_SIGNAL_WORDS = ("비싸", "비쌈")
_CHEAP_SIGNAL_WORDS = ("저렴", "괜찮", "무난")


def _primary_status(judgments: list[dict]) -> str | None:
    """미지원이 아닌 첫 품목의 판정 상태 — 시작 문장 선택 기준(다품목이면 첫 번째 기준)."""
    for j in judgments:
        if j["status"] != _UNSUPPORTED_STATUS:
            return j["status"]
    return None


def _select_opening_line(judgments: list[dict]) -> str | None:
    status = _primary_status(judgments)
    return _STATUS_OPENING_LINES.get(status) if status else None


def _opening_conflicts_with_status(answer: str, status: str | None) -> bool:
    """답변 첫 문장의 어조가 실제 판정(status)과 반대인지 확인 — "오이 지금 비싸?" 재현
    버그(status=쌈인데 "비싼 편이에요!"로 시작)를 잡아내기 위한 하드 개런티."""
    if status is None:
        return False
    first_sentence = re.split(r"[.!\n]", answer, maxsplit=1)[0]
    has_expensive = any(w in first_sentence for w in _EXPENSIVE_SIGNAL_WORDS)
    has_cheap = any(w in first_sentence for w in _CHEAP_SIGNAL_WORDS)
    if status == "비쌈":
        return has_cheap and not has_expensive
    if status in ("적정", "쌈"):
        return has_expensive and not has_cheap
    return False


# [2026-07-15 추가] 실제 관측: "돼지 갈비" 답변에서 실제 평년 대비 등락률(month_diff_pct)이
# +4.7%인데 LLM이 "167.4% 상승"이라고 답변에 써서 완전히 지어낸 수치가 그대로 나간 것을
# 확인함 — 지금까지의 하드개런티는 품목명 언급/판정 어조만 검증했지 답변에 등장하는
# "숫자 자체"가 실제 데이터와 일치하는지는 전혀 검증하지 않고 있었음. 답변에 등장하는
# 모든 퍼센트 수치가 judgments의 실제 diff_pct/month_diff_pct 값 중 하나와 (반올림 오차
# 허용 범위 내에서) 일치하는지 확인 — 근거 없는 수치가 하나라도 있으면 폴백.
_PERCENT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")
_PERCENT_TOLERANCE = 0.15


def _known_percentage_magnitudes(judgments: list[dict]) -> set[float]:
    """실제 diff_pct/month_diff_pct의 절대값 집합.

    [2026-07-15 확인] 절대값으로만 비교하는 이유 — LLM이 "4.8% 하락"처럼 방향을 부호가
    아니라 단어("하락"/"내려서")로 표현하는 경우가 흔한데, 실데이터로 4번 반복 호출해보니
    이런 정상 답변까지 부호가 다르다는 이유로 오탐돼 매번 폴백되는 걸 확인함(단순 서명 비교는
    과함) — 부호는 무시하고 크기(절대값)만 실제 데이터와 맞는지 확인한다.
    """
    values: set[float] = set()
    for j in judgments:
        for field in ("diff_pct", "month_diff_pct"):
            value = j.get(field)
            if value is not None:
                values.add(round(abs(value), 1))
    return values


def _answer_has_fabricated_percentage(answer: str, judgments: list[dict]) -> bool:
    known_magnitudes = _known_percentage_magnitudes(judgments)
    if not known_magnitudes:
        return False
    for raw in _PERCENT_RE.findall(answer):
        pct = abs(float(raw))
        if not any(abs(pct - k) <= _PERCENT_TOLERANCE for k in known_magnitudes):
            return True
    return False


def _compound_base(item_name: str) -> str | None:
    """"돼지 갈비" -> "돼지". 합성(품목+부위) 이름이 아니면 None."""
    return item_name.split(" ", 1)[0] if " " in item_name else None


_SPECIES_PROXIMITY_WINDOW = 10

# [2026-07-15 (5) 추가] "계란 특란10구"처럼 kind_name 자체가 "품종+수량단위" 합성인 경우,
# LLM이 자연스럽게 "특란"(품종)을 생략하고 "30구"(수량단위)만 말하는 경우가 실제로
# 확인됨(예: "계란 30구는 현재가 ..."). core(예: "특란30구") 전체 일치만 보면 이런
# 정상 답변도 "품목명 누락"으로 오판해 불필요하게 딱딱한 템플릿으로 폴백하던 문제 —
# core 끝의 숫자+단위(예: "30구", "10kg", "100개")만으로도 언급된 것으로 인정.
_TRAILING_QUANTITY_RE = re.compile(r"(\d+(?:\.\d+)?[가-힣]+)$")


def _judgment_mentioned(item_name: str, answer: str, ambiguous_species: bool) -> bool:
    """답변이 이 판정 항목을 실제로 언급하고 있는지 확인.

    [2026-07-15 확인] "돼지 갈비"처럼 "품목 부위" 합성 이름은 LLM이 자연스럽게 "돼지"를
    생략하고 "갈비"라고만 쓰는 경우가 흔해서(문맥상 이미 돼지고기 얘기라 중복 언급을
    피함), 전체 문자열을 그대로 대조하면 정상 답변인데도 불필요하게 템플릿로 폴백되는
    문제가 있었음 — _product_core_name()과 동일한 이유로, 부위명(마지막 토큰)만으로도
    언급된 것으로 인정한다.

    [2026-07-15 코드 리뷰 반영] 단, 이번 판정 목록에 서로 다른 축종(예: 돼지+소)이 함께
    섞여 있으면(ambiguous_species=True) 부위명만으론 어느 축종 얘기인지 모호함 —
    "돼지 갈비" 판정인데 답변엔 "소 갈비"만 있어도 "갈비"만 있으면 잘못 통과해버림.
    처음엔 "품목명(base)도 답변 어딘가에 있으면 통과"로 짰는데, "돼지고기랑 소고기
    가격을 보면, 소 갈비는..."처럼 서두에 "돼지고기"가 언급되고 실제로는 "소 갈비"만
    설명하는 문장에서 여전히 통과해버리는 걸 직접 테스트로 확인함 — 단순 존재 여부가
    아니라, 부위명이 등장하는 바로 그 위치 근처(앞 10자 이내)에 품목명이 실제로 붙어
    있는지까지 확인해야 함. 축종이 하나뿐이면(기존처럼) 부위명만으로 충분.
    """
    if item_name in answer:
        return True
    core = item_name.rsplit(" ", 1)[-1]
    qty_match = _TRAILING_QUANTITY_RE.search(core)
    core_candidates = [core, qty_match.group(1)] if qty_match else [core]
    if not ambiguous_species:
        return any(c in answer for c in core_candidates)
    base = _compound_base(item_name)
    if base is None:
        return any(c in answer for c in core_candidates)
    for candidate in core_candidates:
        for match in re.finditer(re.escape(candidate), answer):
            window_start = max(0, match.start() - _SPECIES_PROXIMITY_WINDOW)
            if base in answer[window_start : match.start()]:
                return True
    return False


def _price_facts(judgments: list[dict], substitutes: list[str]) -> str:
    """LLM에게 근거로 넘겨줄 판정 데이터 — 이 안에 없는 수치는 LLM이 지어내면 안 됨."""
    lines = []
    for j in judgments:
        if j["status"] == _UNSUPPORTED_STATUS:
            lines.append(f"- {j['item_name']}: 가격 데이터 없음(지원하지 않는 품목 — 가격·판정을 지어내지 말 것)")
            continue
        sign = "+" if j["diff_pct"] >= 0 else ""
        today_price = j.get("today_price")
        if today_price is not None:
            # [2026-07-14 추가] today_price가 당일가 결측으로 며칠 전 값(dpr2~dpr5 fallback)을
            # 대신 쓴 경우, "현재가"라고만 하면 사용자가 오늘 가격으로 오해할 수 있어
            # price_as_of("1주일전" 등)를 그대로 문구에 노출 — LLM이 마치 당일가인 것처럼
            # 말하지 않도록 데이터 단계에서부터 명시.
            price_as_of = j.get("price_as_of")
            price_label = "현재가" if price_as_of in (None, "당일") else f"{price_as_of} 가격(당일 데이터 미반영)"
            # [2026-07-14 라벨 수정] diff_pct는 실제로 1주일전(dpr3) vs 1개월전(dpr5) 계산이라
            # "평년 대비"가 아니라 "1개월 전 대비"가 맞는 라벨 (계산 자체는 변경 없음)
            line = f"- {j['item_name']}: {price_label} {j['today_price']}원/{j.get('unit', '-')}, 1개월 전 대비 {sign}{j['diff_pct']}% ({j['status']})"
        else:
            line = f"- {j['item_name']}: 1개월 전 대비 {sign}{j['diff_pct']}% ({j['status']}) (현재가 데이터 없음 — 금액을 지어내지 말 것)"
        month_diff = j.get("month_diff_pct")
        if month_diff is not None:
            msign = "+" if month_diff >= 0 else ""
            # [2026-07-15 (8) 수정] month_diff_pct = 화면에 표시되는 현재가(1주일전) vs
            # 평년(dpr7) → "현재가는 ~원, 평년 대비 X%"라고 답할 때 실제로 같은 시점
            # 가격끼리 비교되도록 함(이전엔 1개월전 가격 기준이라 표시 가격과 시점이 어긋났음)
            line += f", 평년 대비 {msign}{month_diff}%"
        lines.append(line)
    if substitutes:
        lines.append(f"- 대체 가능 품목: {', '.join(substitutes)}")
    else:
        # 명시적으로 "없음"을 알려주지 않으면 LLM이 자체적으로 대체품을 지어내는 경우가 있어 방지
        lines.append("- 대체 품목 데이터: 없음 (대체품을 절대 언급하거나 추천하지 말 것)")
    return "\n".join(lines)


async def generate_answer_node(state: AgentState) -> dict[str, Any]:
    """판정 결과를 LLM으로 자연어 답변 생성 — 실패 시 고정 템플릿으로 폴백."""
    if state.get("route") == "knowledge":
        return {"answer": state.get("knowledge_result", ANSWER_NO_DATA)}

    comparison = state.get("comparison")
    if comparison:
        return {"answer": _generate_comparison_answer(comparison, state.get("user_query", ""))}

    processed_prices = state.get("processed_prices")
    if processed_prices:
        return {"answer": _generate_processed_price_answer(processed_prices, state.get("user_query", ""))}

    judgments = state.get("judgment", [])
    if not judgments:
        return {"answer": ANSWER_NO_DATA}

    substitutes = state.get("substitutes") or []
    print(f"[generate_answer_node] substitutes: {substitutes}")

    # [2026-07-14 수정] 기존엔 여기서 ANSWER_PRICE_LINE만으로 직접 lines를 만들어서
    # today_price/unit(실제 가격 금액), week/month 대비 추세가 LLM 컨텍스트에 전혀 안 들어가고 있었음
    # (판정 상태 문구만 들어감 — "가격 정보가 답변에 안 나온다"는 문제의 원인).
    # 이미 있던 _price_facts()가 정확히 이 데이터를 다 채워서 만들어주는 함수인데 호출이 안 되고
    # 있었던 것 — 이제 그대로 재사용.
    primary_status = _primary_status(judgments)
    opening_line = _select_opening_line(judgments)
    species_bases = {b for j in judgments if (b := _compound_base(j["item_name"])) is not None}
    ambiguous_species = len(species_bases) > 1
    context_parts = [
        f"사용자 질문: {state.get('user_query', '')}",
    ]
    if opening_line:
        context_parts.append(
            f'필수 시작 문장(반드시 이 문장을 그대로 답변의 첫 문장으로 사용할 것 — '
            f'다른 표현으로 바꾸거나 생략하지 말 것): "{opening_line}"'
        )
    context_parts += [
        "가격 판정 결과:",
        _price_facts(judgments, substitutes),
    ]
    context = "\n".join(context_parts)

    try:
        answer = _invoke_with_prompts(ANSWER_GENERATION_SYSTEM_PROMPT, context)
        # [2026-07-14 추가] 프롬프트에 "품목명을 반드시 언급할 것"을 지시해도 LLM이 가끔
        # 생략하는 경우가 있음(자유 문장 생성이라 확률적) — 어떤 품목에 대한 답변인지는
        # 사용자가 항상 알 수 있어야 하는 하드 요구사항이라, 프롬프트 지시만으론 보장이 안 돼서
        # 코드에서 직접 검증하고 누락 시 이미 품목명을 포함하는 템플릿 답변으로 폴백시킴.
        if not any(_judgment_mentioned(j["item_name"], answer, ambiguous_species) for j in judgments):
            print(f"[generate_answer_node] LLM 답변에 품목명 누락, 템플릿 답변으로 폴백: {answer!r}")
            answer = _template_answer(judgments, substitutes)
        elif _opening_conflicts_with_status(answer, primary_status):
            # [2026-07-14 추가] "오이 지금 비싸?"(status=쌈)를 5번 호출 중 4번이 "지금은
            # 조금 비싼 편이에요!"로 시작해 실제 판정과 정반대로 답하는 걸 실제로 확인함 —
            # 위에서 시작 문장을 지정해줘도 LLM이 어길 수 있으니 최종 방어선으로 검증.
            print(f"[generate_answer_node] 첫 문장이 판정 결과와 모순, 템플릿 답변으로 폴백: {answer!r}")
            answer = _template_answer(judgments, substitutes)
        elif _answer_has_fabricated_percentage(answer, judgments):
            # [2026-07-15 추가] "돼지 갈비" 답변에서 실제 평년 대비 등락률(+4.7%)과 전혀
            # 무관한 "167.4% 상승"이라는 수치가 그대로 나간 걸 실제로 확인함 — 품목명·어조
            # 검증만으론 못 잡는 완전히 지어낸 숫자를 잡기 위한 최종 방어선.
            print(f"[generate_answer_node] 답변에 근거 없는 퍼센트 수치 발견, 템플릿 답변으로 폴백: {answer!r}")
            answer = _template_answer(judgments, substitutes)
    except Exception as e:
        # 함수 docstring에 원래 "실패 시 고정 템플릿으로 폴백"이라고 적혀 있었는데
        # 실제로는 이 폴백이 연결돼 있지 않았음 — _template_answer()도 같이 살려서 연결함.
        print(f"[generate_answer_node] LLM 호출 실패, 템플릿 답변으로 폴백: {e!r}")
        answer = _template_answer(judgments, substitutes)

    return {"answer": answer}


def generate_offtopic_node(state: AgentState) -> dict[str, Any]:
    return {"answer": OFFTOPIC_RESPONSE}
