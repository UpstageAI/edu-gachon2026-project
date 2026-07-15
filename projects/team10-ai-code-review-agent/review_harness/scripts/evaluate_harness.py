"""리뷰 하네스의 "선택 정확도"를 fixture로 측정하는 평가 스크립트.

하네스(PolicyHarness)는 PR을 보고 검토 절차(skill), 지식 카드(knowledge card),
정책 유형(policy_type)을 고른다. 이 파일은 미리 만든 정답표(fixture)와 대조해
그 선택이 얼마나 정확한지 recall/precision으로 계산한다.

- recall(재현율)  : 골라야 할 정답 중 실제로 고른 비율(놓치지 않았는가).
- precision(정밀도): 고른 것 중 정답인 비율(엉뚱한 걸 고르지 않았는가).

또한 정책 컨텍스트를 얼마나 줄였는지(context reduction)도 측정한다. 이전 방식
(무조건 상위 3개 / 전체 정책)보다 우리 하네스가 모델에 넣는 글자 수를 얼마나
아꼈는지를 비율로 보여 준다. main()은 이를 실행해 하나라도 기준 미달이면 1을
반환하므로 CI에서 회귀 방지용으로 쓸 수 있다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from backend.app.core.routing import extract_features, select_route
from backend.app.core.schemas import ReviewRequest
from backend.app.services.policy_harness import PolicyHarness
from backend.app.services.rag import LocalPolicyIndex

# 정답표(fixture) JSON의 기본 경로. main()에서 명령행 인자로 바꿀 수 있다.
DEFAULT_FIXTURES = Path("review_harness/evaluation/policy-selection-fixtures.json")


def evaluate_harness(
    fixtures_path: Path = DEFAULT_FIXTURES,
    harness_root: Path = Path("review_harness"),
    policy_root: Path = Path("policies"),
) -> dict[str, Any]:
    """fixture들을 하나씩 돌려 하네스 선택 정확도와 컨텍스트 감축률을 집계해 dict로 돌려준다."""
    fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))
    harness = PolicyHarness(harness_root)
    policy_index = LocalPolicyIndex(policy_root)
    # 저장소 정책 전체의 글자 수 합계. "전체를 다 넣었다면" 기준선을 만드는 데 쓴다.
    all_policy_chars = sum(len(chunk.content) for chunk in policy_index.load_chunks())
    # 아래 변수들은 모든 fixture를 돌며 값을 누적하는 "카운터"다. 이름 규칙:
    # *_hits=정답과 겹친 개수(recall 분자), *_expected=정답 개수(recall 분모),
    # *_allowed_hits/*_labeled_selected=precision 계산용, *_selected=고른 개수.
    skill_hits = 0
    skill_expected = 0
    skill_allowed_hits = 0
    skill_labeled_selected = 0
    card_hits = 0
    card_expected = 0
    card_allowed_hits = 0
    card_labeled_selected = 0
    policy_hits = 0
    policy_expected = 0
    policy_selected = 0
    legacy_policy_hits = 0
    legacy_policy_selected = 0
    selected_policy_chars = 0
    legacy_policy_chars = 0
    cases: list[dict[str, Any]] = []

    for fixture in fixtures:
        # 실제 파이프라인과 똑같은 순서로 재현: 요청 복원 → 특징 추출 → 경로 선택 → 하네스 선택.
        request = ReviewRequest.from_dict(fixture["request"])
        features = extract_features(request, policy_available=policy_index.has_policy())
        route = select_route(features, request.review_mode)
        context = harness.select(request, route)
        # 이 경로가 RAG(정책 검색)를 쓸 때만 정책을 실제로 검색한다. 아니면 빈 리스트.
        policies = (
            policy_index.search(
                request,
                top_k=harness.max_policies_per_batch,
                policy_types=set(context.policy_types) or None,
            )
            if route.use_rag
            else []
        )
        # 비교 대상(legacy): 유형 필터 없이 무조건 상위 3개만 뽑던 옛 방식.
        legacy_policies = policy_index.search(request, top_k=3) if route.use_rag else []
        # 하네스가 고른 것들을 집합(set)으로 모은다. 집합이라야 아래 & 연산으로 정답과 겹침을 센다.
        selected_skills = {skill.skill_id for skill in context.skills}
        selected_cards = {card.card_id for card in context.knowledge_cards}
        selected_policy_types = {policy.policy_type for policy in policies}
        legacy_policy_types = {policy.policy_type for policy in legacy_policies}
        # fixture에 적힌 정답. expected=꼭 골라야 할 것, allowed=골라도 되는 것(없으면 expected와 동일).
        expected_skills = set(fixture.get("expected_skills", []))
        allowed_skills = set(fixture.get("allowed_skills", expected_skills))
        expected_cards = set(fixture.get("expected_cards", []))
        allowed_cards = set(fixture.get("allowed_cards", expected_cards))
        expected_policy_types = set(fixture.get("expected_policy_types", []))
        # A & B = 교집합. len(...)으로 "정답과 겹친 개수"를 구해 누적한다.
        skill_hits += len(selected_skills & expected_skills)
        skill_expected += len(expected_skills)
        skill_allowed_hits += len(selected_skills & allowed_skills)
        skill_labeled_selected += len(selected_skills)
        card_hits += len(selected_cards & expected_cards)
        card_expected += len(expected_cards)
        if allowed_cards:
            # 허용 카드 정답이 정의된 fixture만 precision 계산에 포함한다.
            card_allowed_hits += len(selected_cards & allowed_cards)
            card_labeled_selected += len(selected_cards)
        policy_hits += len(selected_policy_types & expected_policy_types)
        policy_expected += len(expected_policy_types)
        policy_selected += len(selected_policy_types)
        legacy_policy_hits += len(legacy_policy_types & expected_policy_types)
        legacy_policy_selected += len(legacy_policy_types)
        # 실제 모델에 들어갈 정책 글자 수를 새 방식/옛 방식 각각 누적(감축률 계산용).
        selected_policy_chars += sum(len(policy.content) for policy in policies)
        legacy_policy_chars += sum(len(policy.content) for policy in legacy_policies)
        cases.append(
            {
                "id": fixture["id"],
                "route": route.name,
                "skills": sorted(selected_skills),
                "knowledge_cards": sorted(selected_cards),
                "policy_types": sorted(selected_policy_types),
            }
        )

    # "모든 fixture에 전체 정책을 다 넣었다면" 나왔을 글자 수. 감축률의 기준선.
    baseline_policy_chars = all_policy_chars * len(fixtures)
    # 하네스가 실제로 근거로 삼은 출처 ID들을 모은다(설계 출처 + skill/카드가 인용한 출처).
    used_source_ids = set(harness.design_source_ids)
    # .update(...)는 집합에 여러 값을 한꺼번에 추가한다(합집합처럼 누적).
    used_source_ids.update(
        str(source_id)
        for item in harness.manifest["skills"]
        for source_id in item.get("source_ids", [])
    )
    used_source_ids.update(
        str(source_id)
        for card in harness.knowledge_cards
        for source_id in card.get("source_ids", [])
    )
    # 아래 지표들은 모두 "맞은 개수 / 전체 개수". 분모가 0이면 나눗셈 오류를 피해 1.0으로 둔다.
    # (평가할 대상이 아예 없으면 "완벽"으로 간주.) round(x, 4)는 소수 넷째 자리 반올림.
    return {
        "fixture_count": len(fixtures),
        # recall = 정답과 겹친 개수 / 정답 개수.
        "skill_recall": round(skill_hits / skill_expected, 4) if skill_expected else 1.0,
        # precision = 허용된 것과 겹친 개수 / 고른 개수.
        "skill_precision": (
            round(skill_allowed_hits / skill_labeled_selected, 4)
            if skill_labeled_selected
            else 1.0
        ),
        "knowledge_card_recall": (
            round(card_hits / card_expected, 4) if card_expected else 1.0
        ),
        "knowledge_card_precision": (
            round(card_allowed_hits / card_labeled_selected, 4)
            if card_labeled_selected
            else 1.0
        ),
        "source_count": len(harness.source_ids),
        # 활용률: 등록된 출처 중 실제로 쓰인 비율. max(...,1)로 0 나눗셈을 막는다.
        "source_utilization_rate": round(
            len(used_source_ids & harness.source_ids) / max(len(harness.source_ids), 1),
            4,
        ),
        "knowledge_card_count": len(harness.knowledge_cards),
        # 카드마다 "출처가 있고, 그 출처가 모두 등록된 출처 집합 안에 있는지"를 확인한 비율.
        # A <= B 는 부분집합 검사(A의 모든 원소가 B에 있는가). 근거 없는 카드가 없는지 본다.
        "source_backed_card_rate": round(
            sum(
                bool(card.get("source_ids"))
                and set(str(value) for value in card.get("source_ids", []))
                <= harness.source_ids
                for card in harness.knowledge_cards
            )
            / max(len(harness.knowledge_cards), 1),
            4,
        ),
        "policy_type_recall": round(policy_hits / policy_expected, 4) if policy_expected else 1.0,
        "policy_type_precision": round(policy_hits / policy_selected, 4) if policy_selected else 1.0,
        "legacy_top3_policy_type_precision": (
            round(legacy_policy_hits / legacy_policy_selected, 4)
            if legacy_policy_selected
            else 1.0
        ),
        "selected_policy_chars": selected_policy_chars,
        "legacy_top3_policy_chars": legacy_policy_chars,
        # 감축률 = 1 - (새 방식 글자수 / 비교 글자수). 예: 0.7이면 70% 줄였다는 뜻.
        # vs_legacy: 옛 상위 3개 방식 대비, policy_context: 전체를 다 넣는 것 대비.
        "vs_legacy_context_reduction": (
            round(1 - (selected_policy_chars / legacy_policy_chars), 4)
            if legacy_policy_chars
            else 0.0
        ),
        "all_policy_chars_baseline": baseline_policy_chars,
        "policy_context_reduction": (
            round(1 - (selected_policy_chars / baseline_policy_chars), 4)
            if baseline_policy_chars
            else 0.0
        ),
        "cases": cases,  # fixture별 선택 결과(어떤 skill/카드/정책유형을 골랐는지) 상세.
    }


def main() -> int:
    """CLI 진입점. 평가를 돌려 JSON으로 출력하고, 기준 미달이면 종료코드 1을 돌려준다."""
    # sys.argv는 명령행 인자 목록(argv[0]은 스크립트 이름). 인자를 주면 그 fixture 경로를 쓴다.
    fixtures_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_FIXTURES
    result = evaluate_harness(fixtures_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # 핵심 지표가 하나라도 완벽(1.0)이 아니면 실패로 보고 1 반환(CI가 이를 감지해 막는다).
    if (
        result["skill_recall"] < 1.0
        or result["skill_precision"] < 1.0
        or result["knowledge_card_recall"] < 1.0
        or result["knowledge_card_precision"] < 1.0
        or result["source_backed_card_rate"] < 1.0
        or result["source_utilization_rate"] < 1.0
        or result["policy_type_recall"] < 1.0
    ):
        return 1
    return 0


# 이 파일을 직접 실행할 때만 main()을 돈다(import될 때는 실행되지 않음).
# SystemExit(정수)로 종료코드를 셸에 전달한다.
if __name__ == "__main__":
    raise SystemExit(main())
