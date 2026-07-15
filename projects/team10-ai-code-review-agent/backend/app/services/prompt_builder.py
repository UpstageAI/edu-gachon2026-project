"""프롬프트 빌더: 리뷰 요청(ReviewRequest)을 모델에 보낼 메시지로 조립하는 단계.

라우팅 다음, 실제 모델 호출(llm.py) 직전 단계다. 하는 일은 크게 세 가지다.
1) 어떤 파일/patch를 프롬프트에 넣을지 "예산(budget)" 안에서 고른다. 큰 PR을
   통째로 넣으면 토큰이 넘치므로, 위험/신호가 큰 파일부터 우선 담고 글자 수를 제한한다.
2) 경로(route)별 검토 지침과 출력 JSON 형식을 담은 system/user 메시지를 만든다.
3) 파일이 많으면 여러 "배치(batch)"로 쪼개, 배치마다 프롬프트를 따로 만든다.

핵심 함수:
- build_review_messages : 배치 하나에 대한 [system, user] 메시지 목록을 만든다.
- build_review_prompt_batches : 전체 PR을 배치들로 나눠 각각의 프롬프트를 만든다.

주의: 이 파일의 한국어/영어 문자열은 모델에게 주는 지시문(프롬프트)이므로 내용이다.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace

from backend.app.core.routing import HIGH_RISK_PATH_KEYWORDS
from backend.app.core.schemas import (
    ChangedFilePayload,
    PolicyChunk,
    ReviewHarnessContext,
    ReviewRequest,
    ReviewRoute,
)
from backend.app.core.security import mask_secrets
from backend.app.services.policy_harness import PolicyHarness
from backend.app.services.rag import rank_policy_chunks


def _route_instructions(route: ReviewRoute) -> list[str]:
    """경로(route)에 맞는 검토 지침 문장들을 돌려준다(모델에게 주는 지시문).

    경로마다 집중할 관점이 다르다: 실패 경로는 최소 수정, 심층 경로는 복잡도·
    아키텍처, 표준 경로는 저장소 정책 준수.
    """
    if route.name == "simple_failure_review":
        return [
            "Focus on the failing syntax, lint, or test evidence and the smallest actionable fix.",
            "Do not expand the review into unrelated architecture or style commentary.",
        ]
    if route.name == "deep_quality_review":
        return [
            (
                "Provide an independent second perspective instead of repeating the standard "
                "policy review."
            ),
            (
                "Analyze time complexity for changed execution paths when the diff provides "
                "enough evidence; name the input variable and estimated Big-O."
            ),
            (
                "Analyze space complexity and memory growth when collections, caching, "
                "buffering, recursion, or large payloads are affected."
            ),
            (
                "Look for behavior-preserving simplification: duplicated branches, unnecessary "
                "state, avoidable queries or loops, and smaller interfaces."
            ),
            (
                "Consider architecture, security, failure isolation, maintainability, and "
                "operational impact."
            ),
            (
                "Do not invent complexity problems. Omit a category when the supplied diff is "
                "insufficient to support a finding."
            ),
        ]
    return [
        "Treat retrieved repository policies as the authoritative review criteria.",
        "Cite policy_source exactly as supplied when a finding is grounded in a retrieved policy.",
        "Do not cite a policy that does not directly support the finding.",
    ]


REVIEW_QUALITY_INSTRUCTIONS = [
    (
        "Report only actionable issues introduced by the diff; prioritize correctness, security, "
        "data integrity, and reliability."
    ),
    (
        "Each finding must name its trigger, consequence, concrete diff evidence, smallest fix, "
        "and focused verification."
    ),
    (
        "Use only right-side diff lines; omit praise, repeated CI output, subjective style, and "
        "speculation."
    ),
]


# 경로별 프롬프트 예산: (프롬프트에 담을 최대 파일 수, 최대 patch 글자 수).
# 12_000 처럼 밑줄은 자릿수 구분용일 뿐 값은 12000이다. 심층 경로일수록 예산이 크다.
ROUTE_PROMPT_BUDGETS = {
    "simple_failure_review": (8, 12_000),
    "policy_context_review": (20, 30_000),
    "deep_quality_review": (30, 50_000),
}

# 배치 하나에 담을 예산: (배치당 최대 파일 수, 배치당 최대 patch 글자 수).
# 위 전체 예산 안에서 다시 작은 배치들로 나눌 때 쓴다.
ROUTE_BATCH_BUDGETS = {
    "simple_failure_review": (4, 6_000),
    "policy_context_review": (4, 6_000),
    "deep_quality_review": (4, 7_000),
}


@dataclass(frozen=True)
class ReviewPromptBatch:
    """배치 하나에 대한 결과 묶음: 그 배치의 요청/메시지/정책/하네스와 순번 정보."""

    request: ReviewRequest
    messages: list[dict[str, str]]
    policies: list[PolicyChunk]
    harness: ReviewHarnessContext | None
    index: int  # 배치 순번(1부터).
    count: int  # 전체 배치 개수.
    patch_chars: int  # 이 배치가 담은 patch 글자 수 합.

# patch 내용에 이런 단어가 있으면 "보안/민감 신호"로 보고 우선 검토 대상으로 올린다.
REVIEW_SIGNAL_MARKERS = {
    "authorization",
    "credential",
    "database",
    "execute(",
    "permission",
    "secret",
    "subprocess",
    "token",
}


def _file_review_priority(changed_file: ChangedFilePayload) -> tuple[bool, bool, int]:
    """파일의 검토 우선순위를 튜플로 만든다(정렬 키로 쓰인다).

    (경로가 위험한가, patch에 신호어가 있는가, 변경 줄 수) 순서로 담는다. 튜플은
    앞 항목부터 비교되므로, 위험 파일 → 신호 있는 파일 → 변경량 큰 파일 순으로
    우선순위가 매겨진다(True가 False보다 크게 취급됨).
    """
    path = changed_file.path.lower()
    patch = changed_file.patch.lower()
    return (
        any(keyword in path for keyword in HIGH_RISK_PATH_KEYWORDS),
        any(marker in patch for marker in REVIEW_SIGNAL_MARKERS),
        changed_file.changed_lines,
    )


def _changed_file_snapshot(
    request: ReviewRequest,
    route: ReviewRoute,
    budget: tuple[int, int] | None = None,
    prompt_context: dict[str, object] | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """예산 안에서 우선순위 높은 파일들을 골라, 프롬프트용 요약(snapshot)으로 만든다.

    반환: (파일 스냅샷 목록, 얼마나 잘라 냈는지 알려 주는 scope 정보).
    각 스냅샷의 patch는 비밀정보를 가리고(mask_secrets) 길이를 잘라 넣는다.
    """
    # budget이 주어지면 그것을, 아니면 경로 기본 예산을 쓴다. 튜플을 두 변수로 언패킹.
    max_files, max_patch_chars = budget or ROUTE_PROMPT_BUDGETS.get(
        route.name,
        (20, 30_000),
    )
    # 우선순위 높은 순으로 정렬(reverse=True)한 뒤 앞에서 max_files개만 자른다.
    selected_files = sorted(
        request.changed_files,
        key=_file_review_priority,
        reverse=True,
    )[:max_files]
    remaining_patch_chars = max_patch_chars
    snapshots: list[dict[str, object]] = []
    for changed_file in selected_files:
        # 파일당 최대 4000자, 그리고 남은 예산 중 작은 쪽까지만 patch를 넣는다.
        patch = changed_file.patch[: min(4000, remaining_patch_chars)]
        remaining_patch_chars -= len(patch)
        snapshots.append(
            {
                "path": changed_file.path,
                "status": changed_file.status,
                "additions": changed_file.additions,
                "deletions": changed_file.deletions,
                "patch": mask_secrets(patch),
                # patch가 잘렸는지(원본보다 짧은지) 표시해, 모델이 오해하지 않게 한다.
                "patch_truncated": len(patch) < len(changed_file.patch),
            }
        )
        if remaining_patch_chars <= 0:
            break  # patch 예산을 다 쓰면 나머지 파일은 넣지 않는다.
    # scope: 전체 대비 몇 개를 넣었고 잘랐는지 등 "무엇을 생략했는지" 메타 정보.
    scope: dict[str, object] = {
        "total_files": len(request.changed_files),
        "included_files": len(snapshots),
        "files_truncated": len(snapshots) < len(request.changed_files),
        "patch_char_budget": max_patch_chars,
    }
    if prompt_context:
        scope.update(prompt_context)  # 배치 순번 등 추가 정보를 합친다.
    return snapshots, scope


def _selected_files_for_review(
    request: ReviewRequest,
    route: ReviewRoute,
) -> list[ChangedFilePayload]:
    """전체 예산 안에서 리뷰 대상 파일들을 고른다(배치로 나누기 전 단계).

    _changed_file_snapshot과 달리 dict가 아니라 잘라 낸 patch를 가진 파일 객체
    목록을 돌려준다. patch가 없는 파일(내용 없음)은 예산과 무관하게 포함한다.
    """
    max_files, max_patch_chars = ROUTE_PROMPT_BUDGETS.get(route.name, (20, 30_000))
    candidates = sorted(request.changed_files, key=_file_review_priority, reverse=True)[:max_files]
    selected: list[ChangedFilePayload] = []
    remaining_patch_chars = max_patch_chars
    for changed_file in candidates:
        if changed_file.patch:
            if remaining_patch_chars <= 0:
                continue  # patch 예산을 다 쓴 뒤의 patch 있는 파일은 건너뛴다.
            patch = changed_file.patch[: min(4000, remaining_patch_chars)]
            remaining_patch_chars -= len(patch)
            # replace(obj, 필드=값): dataclass의 일부만 바꾼 "복사본"을 만든다(원본 불변).
            selected.append(replace(changed_file, patch=patch))
        else:
            selected.append(changed_file)
    return selected


def _group_files(
    changed_files: list[ChangedFilePayload],
    max_files: int,
    max_patch_chars: int,
) -> list[list[ChangedFilePayload]]:
    """파일 목록을 배치(그룹)들로 나눈다. 각 배치는 파일 수/글자 수 한도를 지킨다.

    현재 배치에 파일을 계속 담다가, 파일 수가 차거나 글자 수 예산을 넘으면 새
    배치를 시작한다. 이렇게 나눠야 배치마다 프롬프트가 토큰 한도를 넘지 않는다.
    """
    groups: list[list[ChangedFilePayload]] = []
    current: list[ChangedFilePayload] = []
    current_patch_chars = 0
    for changed_file in changed_files:
        patch_chars = len(changed_file.patch)
        # 현재 배치가 비어 있지 않고, 한도(파일 수 또는 글자 수)를 넘기면 끊어 낸다.
        if current and (
            len(current) >= max_files or current_patch_chars + patch_chars > max_patch_chars
        ):
            groups.append(current)
            current = []
            current_patch_chars = 0
        current.append(changed_file)
        current_patch_chars += patch_chars
    if current:
        groups.append(current)  # 마지막으로 담다 만 배치도 추가한다.
    return groups


def build_review_messages(
    request: ReviewRequest,
    route: ReviewRoute,
    policies: list[PolicyChunk],
    budget: tuple[int, int] | None = None,
    prompt_context: dict[str, object] | None = None,
    harness: ReviewHarnessContext | None = None,
) -> list[dict[str, str]]:
    """배치 하나에 대한 [system, user] 메시지 목록을 만든다(모델 입력 완성본).

    파일 스냅샷, 체크 결과, 복잡도 지표, 정책, 검토 지침, 출력 JSON 형식을 하나의
    user 페이로드로 합쳐 JSON 문자열로 직렬화한다. system 메시지에는 전역 규칙을 둔다.
    """
    changed_files, prompt_scope = _changed_file_snapshot(
        request,
        route,
        budget=budget,
        prompt_context=prompt_context,
    )
    # 프롬프트에 실제로 넣은 파일 경로만 모은 집합(set). 아래에서 포함 여부 확인에 쓴다.
    included_paths = {str(item["path"]) for item in changed_files}
    # 프롬프트에 담은 파일에 해당하는 복잡도 지표만 골라 넣는다(없는 파일 지표는 제외).
    complexity_metrics = [
        metric.to_dict()
        for metric in request.complexity_metrics
        if metric.file_path in included_paths
    ]
    payload = {
        "repository": request.repository.full_name,
        "pull_request": {
            "number": request.pull_request.number,
            "title": request.pull_request.title,
            "author": request.pull_request.author,
            "base_sha": request.pull_request.base_sha,
            "head_sha": request.pull_request.head_sha,
        },
        "checks": [
            {
                "kind": check.kind,
                "status": check.status,
                "conclusion": check.conclusion,
                "summary": mask_secrets(check.summary[:3000]),
            }
            for check in request.checks
        ],
        "changed_files": changed_files,
        "complexity_metrics": complexity_metrics,
        "prompt_scope": prompt_scope,
        "policies": [
            {
                "source_path": policy.source_path,
                "section_title": policy.section_title,
                "policy_type": policy.policy_type,
                "content": policy.content[:2500],
                "policy_source": f"{policy.source_path}#{policy.section_title}",
                "retrieval_score": policy.score,
            }
            for policy in policies
        ],
    }
    # 경로별로 허용하는 지적(finding) 최대 개수(상한). 알 수 없으면 6.
    route_max_findings = {
        "simple_failure_review": 3,
        "policy_context_review": 6,
        "deep_quality_review": 8,
    }.get(route.name, 6)
    batch_count = max(1, int((prompt_context or {}).get("batch_count", 1)))
    # 전체 상한을 배치 수로 나눠 배치당 상한을 정한다. ceil로 올림, 최소 1개는 허용.
    batch_max_findings = max(1, math.ceil(route_max_findings / batch_count))

    # system 메시지: 모델 역할과 전역 규칙(JSON만, 한국어 서술 등)을 담는 지시문.
    system = (
        "You are an AI code review agent for GitHub Pull Requests. "
        "Return only valid JSON. Every natural-language value in summary, file_summaries, "
        "findings, suggestions, and evidence MUST be a complete Korean sentence. "
        "English is allowed only for code identifiers, file paths, API names, and policy IDs. "
        "Describe concrete code and behavior changes instead of abstract importance or risk. "
        "Every finding must be grounded in diff, check logs, or provided repository policy. "
        "Do not invent unavailable files, line numbers, policies, or execution behavior."
    )
    # user 메시지 본문: 검토 대상 데이터와 지침, 원하는 출력 형식을 한 dict에 모은다.
    user = {
        "route": route.to_dict(),
        "review_instructions": _route_instructions(route),
        "review_harness": harness.to_dict() if harness is not None else None,
        "review_harness_instructions": [
            "knowledge_cards는 저명한 외부 출처에서 정제한 검토 관점이며 repository 정책이 아니다.",
            "각 card는 evidence_required를 diff에서 확인하고 false_positive_guard를 통과할 때만 사용한다.",
            "card만으로 결함을 단정하거나 source_ids를 policy_source에 쓰지 않는다.",
            "card에서 파생한 finding의 severity는 severity_cap을 넘지 않는다.",
            "모든 finding은 근거로 사용한 선택 card의 card_id를 knowledge_card_id에 정확히 기록한다.",
            "skill_id, card title, source_id를 knowledge_card_id 대신 사용하지 않는다.",
            "evidence_required를 diff에서 입증하지 못하거나 false_positive_guard에 해당하면 finding을 생략한다.",
            "제공된 diff에 코드가 없다는 사실만으로 저장소 전체에 검증, 예외 처리, 테스트가 없다고 단정하지 않는다.",
            "선택 개선안이 아니라 현재 diff가 만드는 재현 가능한 잘못된 동작만 finding으로 작성한다.",
            "finding을 만들기 전에 제공된 모든 line에서 할당, 기본 반환, 검증, fallback 등 주장을 반증하는 코드를 찾고 하나라도 있으면 생략한다.",
            "max_findings는 목표 개수가 아닌 상한이며 입증된 결함이 없으면 빈 findings가 올바른 응답이다.",
            "외부 API·network·LLM 직접 호출 또는 flaky test 주장은 해당 client 호출과 mock·fake 부재가 diff에 함께 보일 때만 작성한다.",
            "cyclomatic complexity 수치를 직접 추측하거나 diff에서 계산하지 않는다. review_payload.complexity_metrics의 Radon 측정값만 사용한다.",
            "복잡도 finding은 after가 threshold를 초과하고 delta가 양수인 항목에만 작성하며 evidence.metric_id에 정확한 metric_id를 기록한다.",
            "복잡도 측정값이 없는 언어나 파일에는 정량적 복잡도 finding을 만들지 않는다.",
        ],
        "finding_contract": {
            "allowed_knowledge_card_ids": (
                [card.card_id for card in harness.knowledge_cards] if harness else []
            ),
            "rule": (
                "각 finding은 위 목록에서 정확히 하나를 knowledge_card_id로 사용한다. "
                "적용 가능한 card가 없으면 finding을 만들지 않는다."
            ),
        },
        "language_contract": {
            "locale": "ko-KR",
            "rule": (
                "summary.change_summary, summary.short_comment, "
                "summary.file_summaries[*].change_summary와 모든 리뷰 설명은 반드시 한국어로 쓴다."
            ),
        },
        "quality_instructions": REVIEW_QUALITY_INSTRUCTIONS,
        "summary_instructions": [
            "change_summary는 이 배치에서 실제로 바뀐 동작, 인터페이스, 데이터 흐름을 구체적으로 요약한다.",
            "file_summaries는 review_payload.changed_files의 모든 파일을 입력 순서대로 한 번씩 포함한다.",
            "파일 경로는 입력값을 정확히 복사하고 입력에 없는 경로를 만들지 않는다.",
            "중요하다, 위험하다 같은 추상적 평가 대신 무엇이 어떻게 변경됐는지 작성한다.",
        ],
        "severity_guide": {
            "high": "merge-blocking risk",
            "medium": "bounded real defect",
            "low": "evidence-backed maintainability or test weakness",
        },
        "max_findings": batch_max_findings,
        "review_payload": payload,
        "output_schema": {
            "summary": {
                "overall_risk": "low|medium|high",
                "short_comment": "체크 실행 결과에 표시할 한 문장 변경 요약",
                "change_summary": "구체적인 배치 단위 변경 요약",
                "file_summaries": [
                    {
                        "file_path": "review_payload.changed_files에 있는 정확한 경로",
                        "change_summary": "해당 파일에서 실제로 변경된 내용",
                    }
                ],
            },
            "findings": [
                {
                    "severity": "low|medium|high",
                    "category": (
                        "functional_correctness|security|data_integrity|reliability|performance|"
                        "test|api_contract|architecture|time_complexity|space_complexity|"
                        "simplification|maintainability"
                    ),
                    "file_path": "path/to/file.py",
                    "line_start": 1,
                    "line_end": 1,
                    "message": "재현 가능한 문제를 한국어로 설명",
                    "suggestion": "구체적인 개선 방법을 한국어로 설명",
                    "evidence": {
                        "trigger": "문제를 발생시키는 입력, 상태 또는 실행 조건",
                        "consequence": "관찰 가능한 실패 또는 유지보수 비용",
                        "supporting_context": "구체적인 diff 또는 check 근거",
                        "metric_id": "복잡도 finding일 때 complexity_metrics의 정확한 metric_id",
                    },
                    "policy_source": "optional policy source",
                    "knowledge_card_id": "finding_contract.allowed_knowledge_card_ids 중 정확히 하나",
                    "confidence": 0.0,
                }
            ],
        },
    }
    # user 본문은 JSON 문자열로 변환해 보낸다. ensure_ascii=False로 한글이 깨지지 않게 한다.
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def build_review_prompt_batches(
    request: ReviewRequest,
    route: ReviewRoute,
    policies: list[PolicyChunk],
    policy_harness: PolicyHarness | None = None,
) -> list[ReviewPromptBatch]:
    """PR 전체를 여러 배치로 나눠, 배치마다 프롬프트를 만들어 목록으로 돌려준다.

    큰 PR을 한 번에 리뷰하면 프롬프트가 커져 품질이 떨어지므로, 파일을 배치로
    쪼갠다. 배치마다 관련 정책/하네스를 따로 골라(RAG) 프롬프트에 실는다.
    """
    selected_files = _selected_files_for_review(request, route)
    max_batch_files, max_batch_patch_chars = ROUTE_BATCH_BUDGETS.get(
        route.name,
        (4, 6_000),
    )
    file_groups = _group_files(selected_files, max_batch_files, max_batch_patch_chars)
    if not file_groups:
        file_groups = [[]]  # 변경 파일이 없어도 빈 배치 하나는 만든다.

    batch_count = len(file_groups)
    batches: list[ReviewPromptBatch] = []
    # enumerate: (순번, 값)을 함께 돌려준다. offset은 0부터라 +1로 1부터 번호를 매긴다.
    for offset, changed_files in enumerate(file_groups):
        batch_index = offset + 1
        batch_paths = {changed_file.path for changed_file in changed_files}
        # 이 배치만의 요청 객체를 만든다. 파일과 (해당 파일의) 복잡도 지표만 남긴다.
        batch_request = replace(
            request,
            changed_files=changed_files,
            complexity_metrics=[
                metric
                for metric in request.complexity_metrics
                if metric.file_path in batch_paths
            ],
        )
        patch_chars = sum(len(changed_file.patch) for changed_file in changed_files)
        # 하네스(검토 skill/카드)를 이 배치에 맞게 고른다(harness가 없으면 None).
        batch_harness = policy_harness.select(batch_request, route) if policy_harness else None
        # RAG를 쓰는 경로면 이 배치와 관련도 높은 정책만 추려 넣는다.
        if policy_harness and route.use_rag:
            batch_policies = rank_policy_chunks(
                policies,
                batch_request,
                top_k=policy_harness.max_policies_per_batch,
                policy_types=set(batch_harness.policy_types) or None,
            )
        else:
            batch_policies = policies  # RAG를 안 쓰면 받은 정책을 그대로 쓴다.
        messages = build_review_messages(
            batch_request,
            route,
            batch_policies,
            budget=(max_batch_files, max_batch_patch_chars),
            prompt_context={
                "original_total_files": len(request.changed_files),
                "selected_total_files": len(selected_files),
                "batch_index": batch_index,
                "batch_count": batch_count,
            },
            harness=batch_harness,
        )
        batches.append(
            ReviewPromptBatch(
                request=batch_request,
                messages=messages,
                policies=batch_policies,
                harness=batch_harness,
                index=batch_index,
                count=batch_count,
                patch_chars=patch_chars,
            )
        )
    return batches
