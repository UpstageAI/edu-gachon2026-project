"""PR 라우팅 로직: "이 PR을 어떤 방식으로 리뷰할지" 결정하는 단계.

리뷰 파이프라인의 앞부분에서 두 가지 일을 한다.
1) extract_features(): PR 요청(diff, 체크 결과 등)에서 라우팅 판단에 필요한
   특징(feature)을 뽑아낸다. 예: 테스트가 실패했는가, 위험 파일이 있는가.
2) select_route(): 그 특징을 보고 세 가지 경로(route) 중 하나를 고른다.
   - simple_failure_review : 문법/린트/테스트가 실패 → 저비용(low) 모델로 원인만 빠르게
   - policy_context_review : 체크 통과 → 표준(medium) 모델 + 저장소 정책 참조
   - deep_quality_review   : 사용자가 심층 리뷰를 직접 요청 → 고비용(high) 모델

경로마다 사용할 모델 추론 강도(model_tier)와 RAG(정책 검색) 사용 여부가 달라진다.
"""

from __future__ import annotations

from backend.app.core.schemas import CheckResultPayload, PullRequestFeatures, ReviewRequest, ReviewRoute

# 파일 경로에 이 단어들이 들어 있으면 "위험 변경"으로 간주한다(인증, 결제, 마이그레이션 등).
# set(집합) 자료형이라 "in"으로 포함 여부를 빠르게 확인할 수 있다.
HIGH_RISK_PATH_KEYWORDS = {
    "auth",
    "iam",
    "jwt",
    "oauth",
    "permission",
    "policy",
    "security",
    "secret",
    "token",
    "payment",
    "billing",
    "migration",
    "migrations",
    "schema",
    "sql",
    "terraform",
    "infra",
    "docker",
    ".github/workflows",
}


def _status_for(checks: list[CheckResultPayload], kind: str) -> str:
    """여러 체크 결과 중 특정 종류(kind: syntax/lint/test)의 최종 상태를 계산한다.

    반환값: "failed" | "passed" | "skipped" | "unknown".
    함수 이름 앞의 밑줄(_)은 "이 파일 안에서만 쓰는 내부 함수"라는 관례적 표시다.
    """
    # kind 문자열을 이름에 포함하는 체크만 골라 리스트로 모은다(리스트 컴프리헨션).
    matched = [check for check in checks if kind in check.kind.lower()]
    if not matched:
        return "unknown"
    # any(...) = 하나라도 참이면 True. 실패가 하나라도 있으면 전체를 실패로 본다.
    if any(check.is_failed for check in matched):
        return "failed"
    if any(check.is_passed for check in matched):
        return "passed"
    return "skipped"


def _risk_files(request: ReviewRequest) -> list[str]:
    """변경된 파일 중 보안/위험 신호가 있는 파일 경로 목록을 만든다."""
    risk_files: list[str] = []
    for changed_file in request.changed_files:
        normalized = changed_file.path.lower()
        # 경로에 위험 키워드가 하나라도 들어 있으면 위험 파일로 분류한다.
        if any(keyword in normalized for keyword in HIGH_RISK_PATH_KEYWORDS):
            risk_files.append(changed_file.path)
            continue  # 경로에서 이미 걸렸으면 patch 검사는 건너뛴다.
        # 경로로는 못 걸렀지만, 변경 내용(patch)에 민감어가 있으면 위험으로 본다.
        patch = changed_file.patch.lower()
        if any(marker in patch for marker in ("password", "token", "secret", "permission")):
            risk_files.append(changed_file.path)
    # set(...)으로 중복 제거 후 sorted(...)로 정렬해 항상 같은 순서를 보장한다.
    return sorted(set(risk_files))


def _quality_review_reasons(features: PullRequestFeatures) -> list[str]:
    """표준 리뷰(policy_context_review)를 고른 이유들을 사람이 읽을 문자열로 모은다.

    이 이유 목록은 나중에 리뷰 댓글/체크 결과에 "왜 이 경로를 택했는지" 근거로 표시된다.
    """
    reasons = ["checks passed or no failing check detected"]
    if features.policy_available:
        reasons.append("repository policy is available")
    else:
        reasons.append("repository policy is unavailable; falling back to general review")
    if features.has_high_risk_files:
        reasons.append("high-risk signals detected; deep review can be requested")
    if features.changed_lines > 600:
        reasons.append("large diff detected; deep review can be requested")
    if features.changed_files_count > 20:
        reasons.append("many changed files detected; deep review can be requested")
    return reasons


def extract_features(request: ReviewRequest, policy_available: bool) -> PullRequestFeatures:
    """PR 요청에서 라우팅에 쓸 특징(feature)을 추출한다.

    policy_available: 이 저장소에 참고할 정책 문서가 있는지 여부(RAG 사용 가능 여부).
    반환하는 PullRequestFeatures 는 select_route()의 입력이 된다.
    """
    # 체크 종류별 상태를 각각 계산한다.
    syntax_status = _status_for(request.checks, "syntax")
    lint_status = _status_for(request.checks, "lint")
    test_status = _status_for(request.checks, "test")
    # 모든 변경 파일의 (추가+삭제) 줄 수를 합산한다(sum + 제너레이터 표현식).
    changed_lines = sum(changed_file.changed_lines for changed_file in request.changed_files)
    risk_files = _risk_files(request)

    # 라우터 신뢰도: 정보가 부족하거나 위험할수록 confidence를 깎는다(0.9에서 시작).
    confidence = 0.9
    if syntax_status == "unknown":
        confidence -= 0.08
    if lint_status == "unknown":
        confidence -= 0.08
    if test_status == "unknown":
        confidence -= 0.08
    if not policy_available:
        confidence -= 0.06
    if risk_files:
        confidence -= 0.05

    return PullRequestFeatures(
        syntax_status=syntax_status,
        lint_status=lint_status,
        test_status=test_status,
        changed_files_count=len(request.changed_files),
        changed_lines=changed_lines,
        risk_files=risk_files,
        policy_available=policy_available,
        # 아무리 낮아도 최소 0.1은 보장하고, 소수점 둘째 자리로 반올림한다.
        router_confidence=max(0.1, round(confidence, 2)),
    )


def select_route(features: PullRequestFeatures, review_mode: str = "auto") -> ReviewRoute:
    """특징을 보고 세 가지 리뷰 경로 중 하나를 결정한다.

    review_mode: "auto"(기본, 자동 판단) 또는 "deep_quality_review"(사용자가 심층 요청).
    분기 순서가 곧 우선순위다: 실패가 최우선, 그다음 심층 요청, 마지막이 표준 리뷰.
    """
    # 1순위: 문법/린트/테스트 중 하나라도 실패하면 원인 진단용 저비용 경로.
    if features.syntax_failed or features.lint_failed or features.test_failed:
        return ReviewRoute(
            name="simple_failure_review",
            model_tier="solar3-low",
            use_rag=False,  # 실패 원인만 보므로 정책 검색은 하지 않는다.
            focus=["failure_summary", "likely_cause", "fix_priority"],
            reasons=["syntax, lint, or test failed"],
            confidence=0.95,
        )

    # 2순위: 사용자가 GitHub Checks 버튼 등으로 심층 리뷰를 직접 요청한 경우.
    if review_mode == "deep_quality_review":
        return ReviewRoute(
            name="deep_quality_review",
            model_tier="solar3-high",
            use_rag=features.policy_available,
            focus=[
                "architecture",
                "security",
                "time_complexity",
                "space_complexity",
                "simplification",
                "maintainability",
            ],
            reasons=["manual deep review requested"],
            # 심층 리뷰는 최소 0.7 신뢰도를 보장한다.
            confidence=max(0.7, features.router_confidence),
        )

    # 3순위(기본값): 체크가 통과한 정상 PR → 정책 기반 표준 리뷰.
    return ReviewRoute(
        name="policy_context_review",
        model_tier="solar3-medium",
        use_rag=features.policy_available,
        focus=["repo_policy", "style", "tests", "api_contract"],
        reasons=_quality_review_reasons(features),
        confidence=features.router_confidence,
    )
