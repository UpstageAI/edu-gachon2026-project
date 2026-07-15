"""도메인 데이터 모델 모음: 프로그램 안에서 주고받는 "데이터 상자"들의 정의.

이 파일에는 실행 로직이 거의 없다. 대신 리뷰 요청/결과/특징 등 데이터를 담는
dataclass(데이터 클래스)들을 모아 둔다. 다른 모든 모듈이 여기 정의된 타입을
가져다 쓰므로, 코드를 읽을 때 가장 먼저 훑어보면 전체 구조가 눈에 들어온다.

핵심 흐름상 중요한 것:
- ReviewRequest  : 리뷰 입력(저장소, PR, 체크 결과, 변경 파일, 정책 등).
- PullRequestFeatures / ReviewRoute : 라우팅 단계의 입력/출력.
- ReviewFinding / ReviewSummary : 모델이 만든 리뷰 결과(지적 사항, 요약).
- ReviewResult   : 위 모든 것을 담은 최종 결과 객체.

파이썬 문법 메모:
- @dataclass(frozen=True) : 값만 담는 "불변" 데이터 상자. 한 번 만들면 필드를
  바꿀 수 없어 안전하다. __init__ 같은 코드를 자동으로 만들어 준다.
- @classmethod from_dict(...) : dict(JSON에서 온 원시 데이터)를 받아 이 클래스
  인스턴스로 만들어 주는 "생성 도우미". cls는 클래스 자신을 가리킨다.
- to_dict() : 반대로, 객체를 다시 dict로 바꿔 JSON 저장/응답에 쓴다.
- @property : 괄호 없이 obj.x 처럼 접근하지만 실제로는 계산해서 값을 주는 필드.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

# dict[str, Any] = "문자열 키에 아무 값이나 담는 사전"이라는 타입에 붙인 짧은 별명.
# 아래에서 JsonDict라고만 쓰면 이 타입을 뜻한다.
JsonDict = dict[str, Any]


def _string(value: Any, default: str = "") -> str:
    """어떤 값이든 안전하게 문자열로 바꾼다. None이면 기본값을 돌려준다.

    JSON에서 온 데이터는 값이 빠져 있거나(None) 타입이 제각각일 수 있어,
    from_dict에서 이 도우미로 방어적으로 변환한다.
    """
    if value is None:
        return default
    return str(value)


def _int(value: Any, default: int = 0) -> int:
    """값을 정수로 바꾼다. 변환할 수 없으면 예외 대신 기본값을 돌려준다."""
    try:
        return int(value)
    except (TypeError, ValueError):
        # int()가 실패할 때 나는 두 예외를 잡아 프로그램이 죽지 않게 한다.
        return default


@dataclass(frozen=True)
class RepositoryPayload:
    """리뷰 대상 저장소 정보(GitHub owner/name 등)."""

    provider: str
    owner: str
    name: str
    default_branch: str = "main"  # = 뒤는 값을 안 주면 쓰는 기본값이다.

    @classmethod
    def from_dict(cls, payload: JsonDict) -> "RepositoryPayload":
        # payload.get("provider") 는 키가 없으면 None을 주고, _string이 "github"로 보정한다.
        return cls(
            provider=_string(payload.get("provider"), "github"),
            owner=_string(payload.get("owner")),
            name=_string(payload.get("name")),
            default_branch=_string(payload.get("default_branch"), "main"),
        )

    @property
    def full_name(self) -> str:
        # "owner/name" 형태의 전체 이름을 그때그때 조합해 돌려준다.
        return f"{self.owner}/{self.name}"


@dataclass(frozen=True)
class PullRequestPayload:
    """PR 자체의 메타데이터(번호, 제목, 작성자, 커밋 SHA, 브랜치)."""

    number: int
    title: str
    author: str
    base_sha: str  # PR이 갈라져 나온 기준 커밋.
    head_sha: str  # PR의 최신 커밋(리뷰 대상).
    base_branch: str
    head_branch: str

    @classmethod
    def from_dict(cls, payload: JsonDict) -> "PullRequestPayload":
        return cls(
            number=_int(payload.get("number")),
            title=_string(payload.get("title")),
            author=_string(payload.get("author")),
            base_sha=_string(payload.get("base_sha")),
            head_sha=_string(payload.get("head_sha")),
            base_branch=_string(payload.get("base_branch"), "main"),
            head_branch=_string(payload.get("head_branch")),
        )


@dataclass(frozen=True)
class CheckResultPayload:
    """CI 체크 하나의 결과(예: lint 통과, test 실패)."""

    kind: str  # 체크 종류(syntax/lint/test 등)를 구분하는 이름.
    status: str
    conclusion: str
    summary: str = ""
    log_uri: str | None = None  # str | None = "문자열이거나 없음(None)".

    @classmethod
    def from_dict(cls, payload: JsonDict) -> "CheckResultPayload":
        return cls(
            kind=_string(payload.get("kind"), "unknown"),
            status=_string(payload.get("status"), "unknown"),
            conclusion=_string(payload.get("conclusion"), "unknown"),
            summary=_string(payload.get("summary")),
            log_uri=payload.get("log_uri"),
        )

    @property
    def is_failed(self) -> bool:
        # GitHub이 실패를 나타내는 여러 표현 중 하나라도 해당하면 실패로 본다.
        failed_values = {"failed", "failure", "error", "timed_out", "cancelled"}
        return self.status.lower() in failed_values or self.conclusion.lower() in failed_values

    @property
    def is_passed(self) -> bool:
        passed_values = {"passed", "success", "completed"}
        return self.conclusion.lower() in passed_values or (
            self.status.lower() == "completed" and self.conclusion.lower() == "success"
        )


@dataclass(frozen=True)
class ChangedFilePayload:
    """PR에서 바뀐 파일 하나. patch(diff 텍스트)와 원본/변경본 내용을 담는다."""

    path: str
    status: str = "modified"
    additions: int = 0
    deletions: int = 0
    patch: str = ""  # diff 형식의 변경 내용(+/- 로 시작하는 줄들).
    base_content: str = ""  # 변경 전 파일 전체(심층 리뷰의 복잡도 측정에 사용).
    head_content: str = ""  # 변경 후 파일 전체.

    @classmethod
    def from_dict(cls, payload: JsonDict) -> "ChangedFilePayload":
        return cls(
            # GitHub API는 "filename"을, 내부 요청은 "path"를 쓰므로 둘 다 받아들인다.
            path=_string(payload.get("path") or payload.get("filename")),
            status=_string(payload.get("status"), "modified"),
            additions=_int(payload.get("additions")),
            deletions=_int(payload.get("deletions")),
            patch=_string(payload.get("patch")),
            base_content=_string(payload.get("base_content")),
            head_content=_string(payload.get("head_content")),
        )

    @property
    def changed_lines(self) -> int:
        return self.additions + self.deletions


@dataclass(frozen=True)
class GitHubPayload:
    """GitHub webhook 관련 식별자들(어떤 이벤트/설치/체크에서 왔는지)."""

    run_id: str = ""
    event_name: str = "pull_request"
    delivery_id: str = ""
    installation_id: str = ""  # GitHub App이 설치된 위치 식별자(토큰 발급에 필요).
    check_run_id: str = ""

    @classmethod
    def from_dict(cls, payload: JsonDict | None) -> "GitHubPayload":
        payload = payload or {}  # None이 들어와도 빈 dict로 바꿔 안전하게 처리한다.
        return cls(
            run_id=_string(payload.get("run_id")),
            event_name=_string(payload.get("event_name"), "pull_request"),
            delivery_id=_string(payload.get("delivery_id")),
            installation_id=_string(payload.get("installation_id")),
            check_run_id=_string(payload.get("check_run_id")),
        )


@dataclass(frozen=True)
class ComplexityMetric:
    """Radon으로 측정한 함수 하나의 순환 복잡도(cyclomatic complexity) 변화.

    심층 리뷰에서만 채워지며, before/after/delta로 "이 PR이 복잡도를 얼마나 올렸는지"를
    정량적으로 보여 준다. 모델이 복잡도 수치를 추측하지 못하게 하는 근거로도 쓰인다.
    """

    metric_id: str  # 파일+함수 단위의 고유 식별자.
    tool: str
    metric: str
    file_path: str
    symbol: str  # 측정 대상 함수 이름.
    line_start: int
    before: int  # 변경 전 복잡도.
    after: int  # 변경 후 복잡도.
    delta: int  # after - before (양수면 복잡도가 증가).
    threshold: int  # 이 값을 넘으면 문제로 본다(기본 15).
    exceeded_threshold: bool
    rank_before: str  # Radon의 A~F 등급.
    rank_after: str

    @classmethod
    def from_dict(cls, payload: JsonDict) -> "ComplexityMetric":
        return cls(
            metric_id=_string(payload.get("metric_id")),
            tool=_string(payload.get("tool"), "radon"),
            metric=_string(payload.get("metric"), "cyclomatic_complexity"),
            file_path=_string(payload.get("file_path")),
            symbol=_string(payload.get("symbol")),
            line_start=_int(payload.get("line_start")),
            before=_int(payload.get("before")),
            after=_int(payload.get("after")),
            delta=_int(payload.get("delta")),
            threshold=_int(payload.get("threshold"), 15),
            exceeded_threshold=bool(payload.get("exceeded_threshold", False)),
            rank_before=_string(payload.get("rank_before"), "A"),
            rank_after=_string(payload.get("rank_after"), "A"),
        )

    def to_dict(self) -> JsonDict:
        # asdict(...)는 dataclass의 모든 필드를 dict로 자동 변환해 준다.
        return asdict(self)


@dataclass(frozen=True)
class ReviewRequest:
    """리뷰 파이프라인 전체의 입력. 위에서 정의한 조각들을 하나로 묶는다.

    field(default_factory=list) : 리스트처럼 "매번 새로 만들어야 하는" 기본값은
    이렇게 지정한다(모든 인스턴스가 같은 리스트를 공유하는 버그를 막기 위함).
    """

    repository: RepositoryPayload
    pull_request: PullRequestPayload
    checks: list[CheckResultPayload] = field(default_factory=list)
    changed_files: list[ChangedFilePayload] = field(default_factory=list)
    repository_policies: list[PolicyChunk] = field(default_factory=list)
    complexity_metrics: list[ComplexityMetric] = field(default_factory=list)
    github: GitHubPayload = field(default_factory=GitHubPayload)
    review_mode: str = "auto"  # "auto" 또는 "deep_quality_review".

    @classmethod
    def from_dict(cls, payload: JsonDict) -> "ReviewRequest":
        # 중첩된 JSON을 각 조각의 from_dict로 재귀적으로 변환한다.
        # [X.from_dict(i) for i in ...] = 리스트의 각 원소를 변환한 새 리스트.
        return cls(
            repository=RepositoryPayload.from_dict(payload.get("repository", {})),
            pull_request=PullRequestPayload.from_dict(payload.get("pull_request", {})),
            checks=[CheckResultPayload.from_dict(item) for item in payload.get("checks", [])],
            changed_files=[
                ChangedFilePayload.from_dict(item) for item in payload.get("changed_files", [])
            ],
            repository_policies=[
                # **item = dict의 키/값을 그대로 인자로 펼쳐 넣는 문법(언팩).
                PolicyChunk(**item) for item in payload.get("repository_policies", [])
            ],
            complexity_metrics=[
                ComplexityMetric.from_dict(item) for item in payload.get("complexity_metrics", [])
            ],
            github=GitHubPayload.from_dict(payload.get("github")),
            review_mode=_string(payload.get("review_mode"), "auto"),
        )

    def idempotency_key(self) -> str:
        """같은 PR/커밋에 대한 중복 리뷰를 막기 위한 고유 키.

        같은 저장소+PR번호+커밋(head_sha)이면 같은 키가 나오므로, 이미 리뷰한 것을
        다시 실행하지 않도록 판단하는 데 쓴다. 심층 리뷰는 별도 키가 되도록 mode를 덧붙인다.
        """
        key = (
            f"{self.repository.provider}:"
            f"{self.repository.full_name}:"
            f"{self.pull_request.number}:"
            f"{self.pull_request.head_sha}"
        )
        if self.review_mode != "auto":
            key = f"{key}:{self.review_mode}"
        return key

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class PullRequestFeatures:
    """라우팅 판단에 쓰는 추출된 특징(routing.py의 extract_features 결과)."""

    syntax_status: str
    lint_status: str
    test_status: str
    changed_files_count: int
    changed_lines: int
    risk_files: list[str]
    policy_available: bool
    router_confidence: float

    # 아래 @property들은 "..._status == 'failed'" 같은 조건을 읽기 쉬운 이름으로 감싼다.
    @property
    def syntax_failed(self) -> bool:
        return self.syntax_status == "failed"

    @property
    def lint_failed(self) -> bool:
        return self.lint_status == "failed"

    @property
    def test_failed(self) -> bool:
        return self.test_status == "failed"

    @property
    def has_high_risk_files(self) -> bool:
        return bool(self.risk_files)  # 리스트가 비어 있지 않으면 True.

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class ReviewRoute:
    """선택된 리뷰 경로(select_route의 결과). 어떤 모델/전략을 쓸지 담는다."""

    name: str  # simple_failure_review / policy_context_review / deep_quality_review.
    model_tier: str  # solar3-low / -medium / -high (추론 강도).
    use_rag: bool  # 정책 검색(RAG)을 사용할지.
    focus: list[str]  # 이번 리뷰에서 집중할 관점들.
    reasons: list[str]  # 이 경로를 고른 이유(댓글에 근거로 표시).
    confidence: float

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class PolicyChunk:
    """저장소 정책 문서를 검색 단위로 쪼갠 조각(RAG의 검색/주입 단위)."""

    source_path: str  # 이 조각이 나온 정책 파일 경로.
    section_title: str  # 마크다운 제목(섹션 이름).
    content: str
    policy_type: str = "general"  # security/api/test 등으로 분류.
    score: float = 0.0  # 검색 시 계산된 관련도 점수(rank_policy_chunks가 채움).

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class ReviewSourceReference:
    """skill/지식 카드가 근거로 삼은 외부 출처 하나를 사람이 읽을 형태로 담은 것.

    source_ids(문자열 ID)만으로는 무슨 문서인지 알 수 없으므로, 하네스가 sources.json에서
    id→title/url/authority를 찾아 이 형태로 채워 준다. 리뷰 댓글에 "출처: 제목(링크)"로
    그대로 표시해 리뷰 근거를 사람이 바로 확인할 수 있게 하기 위한 필드다.
    """

    source_id: str
    title: str
    url: str
    authority: str  # 출처의 발행 주체(예: "Google Engineering Practices").

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class ReviewSkill:
    """리뷰 하네스가 고른 "검토 절차(skill)". SKILL.md 문서 내용을 담는다."""

    skill_id: str
    title: str
    instructions: str  # SKILL.md에서 읽어 온 검토 지침 텍스트.
    policy_types: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)  # 근거가 된 공식 출처 ID들.
    sources: list[ReviewSourceReference] = field(default_factory=list)  # 위 ID를 사람이 읽을 형태로.
    score: int = 0  # 선택 우선순위 점수.

    def to_dict(self, include_instructions: bool = True) -> JsonDict:
        payload = asdict(self)
        # 저장/응답 용도로는 긴 instructions를 빼서 크기를 줄일 수 있다.
        if not include_instructions:
            payload.pop("instructions", None)  # pop의 두 번째 인자는 "없어도 에러 안 냄".
        return payload


@dataclass(frozen=True)
class ReviewKnowledgeCard:
    """검토 관점을 정리한 "지식 카드". 무엇을 확인하고(check) 어떤 근거가 필요하며
    (evidence_required) 어떤 오탐을 피할지(false_positive_guard)를 담는다.

    카드는 외부 저명 출처를 정제한 것이며, 저장소 정책 자체는 아니다.
    """

    card_id: str
    title: str
    skill_id: str  # 이 카드가 속한 skill.
    check: str
    evidence_required: str
    false_positive_guard: str
    severity_cap: str  # 이 카드로 만든 지적의 심각도 상한.
    source_ids: list[str] = field(default_factory=list)
    sources: list[ReviewSourceReference] = field(default_factory=list)  # 위 ID를 사람이 읽을 형태로.
    forbidden_claim_markers: list[str] = field(default_factory=list)  # 금지된 주장 표현들.
    score: int = 0

    def to_dict(self, include_guidance: bool = True) -> JsonDict:
        payload = asdict(self)
        # 응답에는 모델용 상세 지침을 빼고 식별 정보만 남기기 위한 옵션.
        if not include_guidance:
            payload.pop("check", None)
            payload.pop("evidence_required", None)
            payload.pop("false_positive_guard", None)
            payload.pop("forbidden_claim_markers", None)
        return payload


@dataclass(frozen=True)
class ReviewHarnessContext:
    """하네스 선택 결과 전체: 감지된 신호(signals), 고른 skill/카드, 정책 유형."""

    version: str
    signals: dict[str, list[str]] = field(default_factory=dict)
    skills: list[ReviewSkill] = field(default_factory=list)
    knowledge_cards: list[ReviewKnowledgeCard] = field(default_factory=list)
    policy_types: list[str] = field(default_factory=list)
    candidate_policy_types: list[str] = field(default_factory=list)

    def to_dict(self, include_instructions: bool = True) -> JsonDict:
        # 여기서는 asdict를 쓰지 않고 직접 조립한다. skill/카드마다 상세 지침을 넣을지
        # 뺄지(include_instructions)를 골라서 넘겨야 하기 때문이다.
        return {
            "version": self.version,
            "signals": self.signals,
            "skills": [
                skill.to_dict(include_instructions=include_instructions) for skill in self.skills
            ],
            "knowledge_cards": [
                card.to_dict(include_guidance=include_instructions)
                for card in self.knowledge_cards
            ],
            "policy_types": self.policy_types,
            "candidate_policy_types": self.candidate_policy_types,
        }


@dataclass(frozen=True)
class ReviewFinding:
    """모델이 만든 지적 사항 하나. 최종적으로 GitHub 댓글/inline 코멘트가 된다."""

    severity: str  # high/medium/low.
    category: str  # security, performance 등.
    file_path: str
    line_start: int | None  # None이면 특정 줄이 아니라 파일 전체/요약 수준.
    line_end: int | None
    message: str  # 문제 설명(한국어).
    suggestion: str  # 개선 제안(한국어).
    evidence: JsonDict = field(default_factory=dict)  # 근거(trigger/consequence 등).
    policy_source: str | None = None  # 근거가 된 저장소 정책 출처.
    knowledge_card_id: str | None = None  # 근거로 쓴 지식 카드 ID.
    confidence: float = 0.7

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class FileChangeSummary:
    """파일 하나에 대한 변경 요약(댓글의 "파일별 변경 요약" 표에 들어간다)."""

    file_path: str
    change_summary: str

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class ReviewSummary:
    """리뷰 전체 요약: 위험도, 한 줄 코멘트, 변경 요약, 파일별 요약."""

    route_name: str
    model_tier: str
    overall_risk: str
    short_comment: str
    change_summary: str = ""
    file_summaries: list[FileChangeSummary] = field(default_factory=list)

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class ModelCallUsage:
    """모델 호출 사용량/비용 기록(토큰 수, 지연 시간, 비용 등). 관측·과금 분석용."""

    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    status: str = "completed"
    reasoning_effort: str | None = None
    cost_usd: float = 0.0
    batch_count: int = 1  # 큰 PR은 여러 배치로 나눠 호출하므로 배치 수를 함께 기록.

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class ReviewEvent:
    """리뷰 진행 중 발행되는 이벤트 하나(SSE로 실시간 스트리밍된다)."""

    review_run_id: str
    sequence: int  # 발행 순서(1부터). 클라이언트가 이어받기(재접속)에 사용.
    event_type: str
    payload: JsonDict = field(default_factory=dict)
    # default_factory=time.time : 객체를 만드는 시점의 현재 시각을 자동으로 채운다.
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class ReviewResult:
    """파이프라인의 최종 결과. 저장소에 저장되고 API 응답으로도 나간다.

    to_dict()가 asdict를 쓰지 않고 손수 조립하는 이유: review_harness는 모델용 상세
    지침(instructions)을 빼고(include_instructions=False) 내보내야 하고,
    None일 수도 있는 필드를 조건부로 처리해야 하기 때문이다.
    """

    review_run_id: str
    status: str
    idempotency_key: str
    summary: ReviewSummary
    findings: list[ReviewFinding]
    route: ReviewRoute
    features: PullRequestFeatures
    model_call: ModelCallUsage
    retrieved_policies: list[PolicyChunk] = field(default_factory=list)
    complexity_metrics: list[ComplexityMetric] = field(default_factory=list)
    review_harness: ReviewHarnessContext | None = None
    finding_validation: JsonDict = field(default_factory=dict)  # 검증 단계 통계.
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> JsonDict:
        return {
            "review_run_id": self.review_run_id,
            "status": self.status,
            "idempotency_key": self.idempotency_key,
            "summary": self.summary.to_dict(),
            "findings": [finding.to_dict() for finding in self.findings],
            "route": self.route.to_dict(),
            "features": self.features.to_dict(),
            "model_call": self.model_call.to_dict(),
            "retrieved_policies": [chunk.to_dict() for chunk in self.retrieved_policies],
            "complexity_metrics": [metric.to_dict() for metric in self.complexity_metrics],
            "review_harness": (
                # 삼항식: 조건이 참일 때 값 if 조건 else 거짓일 때 값.
                self.review_harness.to_dict(include_instructions=False)
                if self.review_harness is not None
                else None
            ),
            "finding_validation": self.finding_validation,
            "created_at": self.created_at,
        }
