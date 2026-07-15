"""모델이 만든 지적 사항(finding)을 검증·정규화·랭킹하는 단계.

LLM이 뱉은 결과는 그대로 믿을 수 없다(존재하지 않는 파일 지적, 근거 없는 주장,
중복, 과장된 심각도 등). 이 파일은 그 결과를 걸러 내고 다듬어, 사용자에게 보일
만한 것만 남긴다. 리뷰 파이프라인에서 LLM 호출 바로 다음 단계다.

핵심 함수는 validate_and_rank_findings() 하나이고, 나머지는 그 안에서 쓰는
도우미다. 검증은 대략 이 순서로 진행된다.
1) 실제로 바뀐 파일에 대한 지적인가
2) 내용/제안이 비어 있지 않고 한국어로 쓰였는가
3) 정책 출처/지식 카드가 실제로 존재하는가(없는 근거를 지어내지 않았는가)
4) 지식 카드의 금지 표현/심각도 상한/복잡도 근거 규칙을 지켰는가
5) 지적한 줄이 실제 diff의 우측(추가된) 줄인가
6) 중복 제거 → 심각도순 정렬 → route별 최대 개수로 잘라 내기
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from backend.app.core.schemas import (
    PolicyChunk,
    ReviewFinding,
    ReviewKnowledgeCard,
    ReviewRequest,
    ReviewRoute,
)

# route(리뷰 경로)마다 최종적으로 남길 지적 개수 상한. 저비용 경로는 적게,
# 심층 리뷰는 많이. 노이즈를 줄이려고 개수를 강제로 제한한다.
ROUTE_MAX_FINDINGS = {
    "simple_failure_review": 3,
    "policy_context_review": 6,
    "deep_quality_review": 8,
}

# 모델이 심각도를 제각각으로 표현하므로(critical, p0, minor 등) 세 단계(high/
# medium/low)로 정규화하는 대응표. 알 수 없는 값은 나중에 medium으로 처리한다.
SEVERITY_ALIASES = {
    "critical": "high",
    "blocker": "high",
    "p0": "high",
    "p1": "high",
    "major": "high",
    "high": "high",
    "p2": "medium",
    "minor": "medium",
    "medium": "medium",
    "p3": "low",
    "trivial": "low",
    "info": "low",
    "low": "low",
}

# 정렬용 순위. 숫자가 작을수록 심각도가 높아 위로 온다.
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
# 한글이 한 글자라도 있는지 검사하는 정규식(re.compile은 패턴을 미리 컴파일).
KOREAN_PATTERN = re.compile(r"[가-힣]")
# diff의 hunk 헤더("@@ -a,b +c,d @@")에서 우측(변경 후) 시작 줄 번호(start)와
# 줄 수(count)를 뽑아내는 정규식. (?P<이름>...)은 그 부분에 이름을 붙인 것.
HUNK_HEADER_PATTERN = re.compile(
    r"^@@\s+-\d+(?:,\d+)?\s+\+(?P<start>\d+)(?:,(?P<count>\d+))?\s+@@"
)
# 복잡도(순환 복잡도) 관련 지식 카드의 ID. 이 카드는 특별히 Radon 측정값으로
# 근거를 검증하므로 상수로 따로 둔다.
COMPLEXITY_CARD_ID = "python-cyclomatic-complexity-threshold"


def _right_side_diff_lines(patch: str) -> set[int]:
    """diff(patch)에서 "변경 후 파일 기준으로 실제 존재하는 줄 번호" 집합을 구한다.

    모델이 지적한 줄이 실제로 이번 PR에서 추가/유지된 줄인지 확인하기 위해 쓴다.
    삭제된(-) 줄은 변경 후 파일에 없으므로 제외한다. 반환은 set(집합)이라 "in"으로
    포함 여부를 빠르게 확인할 수 있다.
    """
    lines: set[int] = set()
    current_line: int | None = None
    # splitlines(): 문자열을 줄 단위 리스트로 나눈다.
    for raw_line in patch.splitlines():
        header = HUNK_HEADER_PATTERN.match(raw_line)
        if header:
            # 새 hunk를 만나면 그 hunk의 우측 시작 줄 번호로 카운터를 맞춘다.
            current_line = int(header.group("start"))
            continue
        # 아직 hunk 안이 아니거나 "개행 없음" 표시 줄이면 건너뛴다.
        if current_line is None or raw_line.startswith("\\ No newline"):
            continue
        # 삭제 줄(-로 시작, 단 파일 헤더 '---'는 제외)은 변경 후에 없으므로 센 뒤 넘어간다.
        if raw_line.startswith("-") and not raw_line.startswith("---"):
            continue
        # 여기 온 줄(추가 '+' 또는 문맥 ' ')은 변경 후 파일에 존재하므로 번호를 기록.
        lines.add(current_line)
        current_line += 1
    return lines


def _canonical_policy_sources(policies: list[PolicyChunk]) -> dict[str, str]:
    """실제로 제공된 정책 출처들의 "허용 목록"을 만든다.

    모델이 근거로 댄 policy_source가 진짜 존재하는지 확인할 때 쓴다. 키는 두 가지
    형태("파일#섹션"과 "파일"만)를 모두 받아 주되, 값은 항상 정식 표기인
    "파일#섹션"으로 통일해, 모델이 파일 경로만 적어도 정식 표기로 보정되게 한다.
    setdefault: 그 키가 아직 없을 때만 넣는다(먼저 넣은 값을 덮어쓰지 않음).
    """
    sources: dict[str, str] = {}
    for policy in policies:
        canonical = f"{policy.source_path}#{policy.section_title}"
        sources[canonical] = canonical
        sources.setdefault(policy.source_path, canonical)
    return sources


def _finding_key(finding: ReviewFinding) -> tuple[object, ...]:
    """중복 판정을 위한 지적의 "지문(키)"을 만든다.

    파일/줄/범주/내용이 사실상 같으면 같은 지적으로 본다. 내용은 소문자로 바꾸고
    공백을 하나로 합쳐(split 후 join) 사소한 차이를 무시한다. 튜플로 묶어 set에
    넣고 비교할 수 있게 한다.
    """
    normalized_message = " ".join(finding.message.lower().split())
    return (
        finding.file_path,
        finding.line_start,
        finding.category.lower(),
        normalized_message,
    )


def validate_and_rank_findings(
    request: ReviewRequest,
    route: ReviewRoute,
    policies: list[PolicyChunk],
    findings: list[ReviewFinding],
    knowledge_cards: list[ReviewKnowledgeCard] | None = None,
) -> tuple[list[ReviewFinding], dict[str, Any]]:
    """모델이 만든 findings를 검증·정규화·랭킹해 최종 목록과 통계를 돌려준다.

    반환: (통과한 finding 리스트, report). report는 "무엇을 몇 개 걸러냈는지"의
    통계로, 나중에 관측/디버깅에 쓰인다. 튜플(...)로 두 값을 함께 반환한다.
    """
    # 아래 세 줄은 모두 딕셔너리 컴프리헨션: 리스트를 "키 -> 값" 사전으로 바꾼다.
    # 파일 경로로 변경 파일을 빠르게 찾기 위한 사전.
    changed_files = {changed_file.path: changed_file for changed_file in request.changed_files}
    policy_sources = _canonical_policy_sources(policies)
    # card_id로 지식 카드를 찾는 사전. (knowledge_cards or []): None이면 빈 리스트로.
    cards_by_id = {card.card_id: card for card in knowledge_cards or []}
    # metric_id로 복잡도 측정값을 찾는 사전(복잡도 근거 검증에 사용).
    complexity_metrics = {
        metric.metric_id: metric for metric in request.complexity_metrics
    }
    # 각 항목을 몇 개 받았고/걸러냈고/통과시켰는지 세는 통계 딕셔너리.
    report: dict[str, Any] = {
        "received": len(findings),
        "accepted": 0,
        "unknown_file_dropped": 0,
        "empty_finding_dropped": 0,
        "non_korean_finding_dropped": 0,
        "duplicate_dropped": 0,
        "invalid_line_removed": 0,
        "invalid_policy_source_removed": 0,
        "missing_knowledge_card_dropped": 0,
        "invalid_knowledge_card_dropped": 0,
        "knowledge_card_guard_dropped": 0,
        "invalid_complexity_evidence_dropped": 0,
        "invalid_knowledge_card_ids": [],
        "severity_capped_by_card": 0,
        "over_limit_dropped": 0,
    }
    accepted: list[ReviewFinding] = []  # 최종적으로 통과한 지적들.
    seen: set[tuple[object, ...]] = set()  # 이미 본 지문(중복 검출용).

    # 지적 하나하나에 대해 여러 검증을 통과시키며, 실패하면 continue로 버린다.
    for finding in findings:
        # 검증 1: 실제로 이번 PR에서 바뀐 파일에 대한 지적이어야 한다.
        changed_file = changed_files.get(finding.file_path)
        if changed_file is None:
            report["unknown_file_dropped"] += 1
            continue
        # 검증 2: 문제 설명과 제안이 모두 비어 있지 않아야 한다(strip은 공백 제거).
        if not finding.message.strip() or not finding.suggestion.strip():
            report["empty_finding_dropped"] += 1
            continue
        # 검증 3: 사용자용이므로 한국어가 포함돼야 한다(영어만 있으면 버림).
        if not KOREAN_PATTERN.search(finding.message) or not KOREAN_PATTERN.search(
            finding.suggestion
        ):
            report["non_korean_finding_dropped"] += 1
            continue

        # 심각도를 세 단계로 정규화한다. 표에 없는 값은 medium으로 본다.
        severity = SEVERITY_ALIASES.get(finding.severity.strip().lower(), "medium")
        # 검증 4a: 정책 출처를 댔다면 실제 존재하는 출처여야 한다. 없으면 근거만 지운다
        # (지적 자체는 버리지 않되, 정식 표기로 보정한다).
        policy_source = finding.policy_source
        if policy_source:
            canonical_source = policy_sources.get(policy_source)
            if canonical_source is None:
                policy_source = None
                report["invalid_policy_source_removed"] += 1
            else:
                policy_source = canonical_source

        knowledge_card_id = finding.knowledge_card_id
        evidence = dict(finding.evidence)  # 원본을 건드리지 않도록 복사본으로 다룬다.
        # 검증 4b: 지식 카드가 제공된 리뷰인데 카드 근거가 없으면 버린다(근거 필수).
        if cards_by_id and not knowledge_card_id:
            report["missing_knowledge_card_dropped"] += 1
            continue
        if knowledge_card_id:
            card = cards_by_id.get(knowledge_card_id)
            if card is None:
                # 존재하지 않는 카드 ID를 지어냈으면 버리고, 그 ID를 기록해 둔다.
                report["invalid_knowledge_card_dropped"] += 1
                report["invalid_knowledge_card_ids"].append(knowledge_card_id)
                continue
            else:
                # 카드의 "금지 표현" 검사를 위해 message/suggestion/evidence를 한 덩어리
                # 소문자 텍스트로 합친다. *(...)는 제너레이터를 인자로 펼쳐 넣는 언팩.
                claim_text = " ".join(
                    [
                        finding.message,
                        finding.suggestion,
                        *(str(value) for value in finding.evidence.values()),
                    ]
                ).lower()
                # 카드가 금지한 오탐 유발 표현이 하나라도 있으면 버린다(오탐 방지).
                if any(marker in claim_text for marker in card.forbidden_claim_markers):
                    report["knowledge_card_guard_dropped"] += 1
                    continue
                # 심각도 상한: 카드가 정한 상한보다 더 높게 지적했으면 상한선으로 낮춘다.
                # SEVERITY_ORDER는 high=0이라, 값이 작을수록 심각도가 높다.
                severity_cap = SEVERITY_ALIASES.get(card.severity_cap.lower(), "medium")
                if SEVERITY_ORDER[severity] < SEVERITY_ORDER[severity_cap]:
                    severity = severity_cap
                    report["severity_capped_by_card"] += 1
                # 복잡도 카드는 특별 취급: 모델 주장 대신 Radon 실측값으로 근거를 검증한다.
                if card.card_id == COMPLEXITY_CARD_ID:
                    metric_id = str(evidence.get("metric_id") or "")
                    metric = complexity_metrics.get(metric_id)
                    # 실측이 없거나, 파일 불일치거나, 임계값을 안 넘었거나, 복잡도가
                    # 증가하지 않았으면(delta<=0) 근거 미달로 버린다.
                    if (
                        metric is None
                        or metric.file_path != finding.file_path
                        or not metric.exceeded_threshold
                        or metric.delta <= 0
                    ):
                        report["invalid_complexity_evidence_dropped"] += 1
                        continue
                    # 근거를 실측값으로 덮어써, 모델이 추측한 수치를 신뢰 가능한 값으로 교체.
                    evidence.update(
                        {
                            "metric_id": metric.metric_id,
                            "tool": metric.tool,
                            "metric": metric.metric,
                            "symbol": metric.symbol,
                            "before": metric.before,
                            "after": metric.after,
                            "delta": metric.delta,
                            "threshold": metric.threshold,
                            "trigger": (
                                f"Radon 측정에서 {metric.symbol} 함수의 cyclomatic complexity가 "
                                f"{metric.before}에서 {metric.after}로 증가해 임계값 "
                                f"{metric.threshold}를 초과했습니다."
                            ),
                        }
                    )

        # 검증 5: 지적한 줄이 실제 diff의 우측(변경 후) 줄인지 확인한다.
        line_start = finding.line_start
        line_end = finding.line_end
        if line_start is not None:
            valid_lines = _right_side_diff_lines(changed_file.patch)
            if line_start not in valid_lines:
                # 존재하지 않는 줄이면 줄 정보만 지운다(파일 수준 지적으로 강등).
                line_start = None
                line_end = None
                report["invalid_line_removed"] += 1
            elif line_end is None or line_end < line_start or line_end not in valid_lines:
                # 끝 줄이 이상하면 시작 줄과 같게 맞춰 한 줄짜리로 정리한다.
                line_end = line_start

        # replace(obj, ...): frozen dataclass는 수정이 안 되므로, 지정한 필드만 바꾼
        # "복사본"을 새로 만든다. 여기서 정규화된 값들을 한꺼번에 반영한다.
        normalized = replace(
            finding,
            severity=severity,
            category=finding.category.strip().lower() or "general",
            line_start=line_start,
            line_end=line_end,
            message=finding.message.strip(),
            suggestion=finding.suggestion.strip(),
            evidence=evidence,
            policy_source=policy_source,
            knowledge_card_id=knowledge_card_id,
            # confidence는 0.0~1.0 범위로 강제한다(min/max로 위아래를 자름).
            confidence=max(0.0, min(float(finding.confidence), 1.0)),
        )
        # 검증 6: 앞서 통과한 것과 사실상 같은 지적이면 중복으로 버린다.
        key = _finding_key(normalized)
        if key in seen:
            report["duplicate_dropped"] += 1
            continue
        seen.add(key)
        accepted.append(normalized)

    # 정렬: 심각도(높은 것 먼저) → confidence 높은 순 → 파일명 → 줄 번호.
    # key로 튜플을 주면 앞에서부터 순서대로 비교한다. -finding.confidence처럼 부호를
    # 뒤집으면 "큰 값이 먼저"가 된다. (line_start or 0): None이면 0으로.
    accepted.sort(
        key=lambda finding: (
            SEVERITY_ORDER.get(finding.severity, 1),
            -finding.confidence,
            finding.file_path,
            finding.line_start or 0,
        )
    )
    # route별 상한 개수만큼만 남기고 나머지는 잘라 낸다(없는 route는 기본 6).
    max_findings = ROUTE_MAX_FINDINGS.get(route.name, 6)
    if len(accepted) > max_findings:
        report["over_limit_dropped"] = len(accepted) - max_findings
        accepted = accepted[:max_findings]
    report["accepted"] = len(accepted)
    # 잘못된 카드 ID 목록은 중복 제거 후 정렬해 깔끔하게 보고한다.
    report["invalid_knowledge_card_ids"] = sorted(
        set(report["invalid_knowledge_card_ids"])
    )
    return accepted, report
