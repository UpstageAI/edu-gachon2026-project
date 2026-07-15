"""LLM 클라이언트: 프롬프트를 실제 "리뷰 결과"로 바꾸는 단계.

prompt_builder가 만든 messages(프롬프트)를 받아, 모델을 호출하고 그 응답(JSON)을
ReviewSummary/ReviewFinding 같은 도메인 객체로 변환한다.

두 가지 구현이 있고 config의 llm_mode로 고른다(create_llm_client가 선택).
- MockLLMClient : 실제 모델을 부르지 않는 개발/테스트용 가짜 리뷰어. 같은 입력이면
  항상 같은 결과를 내는 "결정론적(deterministic)" 동작이라 테스트에 좋다.
- LiteLLMClient : litellm 라이브러리로 실제 Solar3 모델을 호출한다. 빈/깨진 응답
  재시도, Langfuse 관측 연동, 응답 JSON 파싱을 담당한다.

두 클래스 모두 LLMClient가 정한 generate_review 형태를 그대로 따른다.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any, Protocol

from backend.app.core.config import Settings
from backend.app.core.schemas import (
    ChangedFilePayload,
    FileChangeSummary,
    ModelCallUsage,
    PolicyChunk,
    ReviewFinding,
    ReviewRequest,
    ReviewRoute,
    ReviewSummary,
)


class LLMClient(Protocol):
    """LLM 클라이언트가 갖춰야 할 "모양"을 정의한 인터페이스.

    Protocol은 덕 타이핑용 인터페이스다. 이 generate_review 메서드만 있으면
    상속 없이도 LLMClient로 취급된다("이 메서드만 있으면 OK"). 덕분에 Mock과
    LiteLLM을 자유롭게 바꿔 끼울 수 있다.
    """

    def generate_review(
        self,
        request: ReviewRequest,
        route: ReviewRoute,
        policies: list[PolicyChunk],
        messages: list[dict[str, str]],
        review_run_id: str | None = None,
        batch_index: int = 1,
        batch_count: int = 1,
    ) -> tuple[ReviewSummary, list[ReviewFinding], ModelCallUsage]:
        # ... 는 "본문 없음"(구현은 각 클래스가 채운다)을 뜻하는 자리표시다.
        ...


def _first_changed_path(request: ReviewRequest) -> str:
    """변경 파일 중 첫 번째 경로를 돌려준다(Mock이 지적을 붙일 대상). 없으면 "unknown"."""
    if request.changed_files:
        return request.changed_files[0].path
    return "unknown"


def _line_for_first_file(request: ReviewRequest) -> int | None:
    """변경 파일이 있으면 1번 줄, 없으면 None(특정 줄 없음)을 돌려준다."""
    if not request.changed_files:
        return None
    return 1


def _fallback_file_change_summary(changed_file: ChangedFilePayload) -> str:
    """모델이 파일 요약을 안 줬을 때 대신 쓸 기본 요약 문장을 만든다.

    변경 상태(status) 영어 코드를 한국어 라벨로 바꾸고 추가/삭제 줄 수를 붙인다.
    """
    status_labels = {
        "added": "새 파일 추가",
        "removed": "파일 삭제",
        "renamed": "파일 이름 변경",
        "modified": "파일 수정",
    }
    # dict.get(키, 기본값): 매핑에 없는 status면 원래 값 또는 "파일 수정"을 쓴다.
    status = status_labels.get(changed_file.status.lower(), changed_file.status or "파일 수정")
    return f"{status}: {changed_file.additions}줄 추가, {changed_file.deletions}줄 삭제"


# 한글 글자 하나라도 있는지 검사하는 정규식(가~힣 = 완성형 한글 범위).
KOREAN_PATTERN = re.compile(r"[가-힣]")


def _korean_text(value: Any) -> str:
    """값을 문자열로 정리하되, 한글이 하나도 없으면 빈 문자열로 버린다.

    프롬프트가 "설명은 한국어로" 요구하므로, 모델이 영어만 준 값은 쓰지 않고
    나중에 한국어 기본값으로 대체하기 위한 방어 장치다.
    """
    # str(value or "") : None이나 빈 값이면 "" 로 만들어 안전하게 처리.
    text = str(value or "").strip()
    return text if KOREAN_PATTERN.search(text) else ""


def _file_summaries_from_payload(
    payload: Any,
    request: ReviewRequest,
) -> list[FileChangeSummary]:
    """모델이 준 파일별 요약을 검증해 정리하고, 빠진 파일은 기본 요약으로 채운다.

    모델이 실제로 바뀌지 않은 엉뚱한 파일을 지어내는 것을 막기 위해, 실제
    변경 파일(allowed_files)에 있는 경로만 받아들인다. 결과는 항상 변경 파일
    전체를 입력 순서대로 하나씩 포함한다.
    """
    # {키: 값 for ...} = 딕셔너리 컴프리헨션. 경로로 빠르게 조회하기 위한 표.
    allowed_files = {changed_file.path: changed_file for changed_file in request.changed_files}
    parsed: dict[str, str] = {}
    # isinstance(x, T): x가 타입 T인지 확인. 모델 응답 형태를 믿지 않고 방어한다.
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            file_path = str(item.get("file_path") or "").strip()
            change_summary = _korean_text(
                item.get("change_summary") or item.get("summary") or ""
            )
            # 실제 변경 파일이고, 한국어 요약이 있고, 아직 안 담은 경로일 때만 채택.
            if file_path in allowed_files and change_summary and file_path not in parsed:
                parsed[file_path] = change_summary

    return [
        FileChangeSummary(
            file_path=changed_file.path,
            # 모델이 준 요약이 있으면 쓰고, 없으면 기본 요약으로 대체한다.
            change_summary=parsed.get(
                changed_file.path,
                _fallback_file_change_summary(changed_file),
            ),
        )
        for changed_file in request.changed_files
    ]


def _fallback_change_summary(request: ReviewRequest) -> str:
    """모델이 전체 변경 요약을 안 줬을 때 쓸 기본 요약(파일 수/추가/삭제 줄 수)."""
    additions = sum(changed_file.additions for changed_file in request.changed_files)
    deletions = sum(changed_file.deletions for changed_file in request.changed_files)
    return (
        f"변경 파일 {len(request.changed_files)}개에서 "
        f"{additions}줄을 추가하고 {deletions}줄을 삭제했습니다."
    )


def _harness_card_contract(messages: list[dict[str, str]]) -> tuple[bool, str | None]:
    """프롬프트에 지식 카드(knowledge card)가 실렸는지, 그 첫 카드 id를 알아낸다.

    반환: (하네스가 있었는가, 사용할 card_id 또는 None). Mock이 지식 카드
    규칙(카드가 있으면 finding에 card_id를 반드시 붙여야 함)을 흉내 내기 위해 쓴다.
    """
    # reversed(...)로 뒤에서부터 훑어 마지막 user 메시지를 먼저 찾는다.
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        try:
            # user 메시지 content는 JSON 문자열이므로 dict로 되돌린다(파싱).
            payload = json.loads(message.get("content") or "{}")
        except json.JSONDecodeError:
            # JSON이 아니면 이 메시지는 건너뛴다.
            continue
        harness = payload.get("review_harness")
        if not isinstance(harness, dict):
            continue
        cards = harness.get("knowledge_cards") or []
        if cards and isinstance(cards[0], dict):
            return True, str(cards[0].get("card_id") or "") or None
        return True, None
    return False, None


class MockLLMClient:
    """개발/테스트용 결정론적 리뷰어(실제 모델을 부르지 않는다).

    경로(route)에 따라 미리 정한 형태의 리뷰를 만들어 낸다. 같은 입력이면 항상
    같은 결과가 나와, 모델 없이도 파이프라인 전체를 빠르게 검증할 수 있다.
    """

    # __init__ 은 객체를 만들 때 한 번 호출되는 초기화 메서드.
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate_review(
        self,
        request: ReviewRequest,
        route: ReviewRoute,
        policies: list[PolicyChunk],
        messages: list[dict[str, str]],
        review_run_id: str | None = None,
        batch_index: int = 1,
        batch_count: int = 1,
    ) -> tuple[ReviewSummary, list[ReviewFinding], ModelCallUsage]:
        """경로별로 정해진 가짜 리뷰(요약, 지적, 사용량)를 만들어 돌려준다."""
        # perf_counter()는 경과 시간 측정용 시계. 나중에 지연 시간(latency)을 잰다.
        start = time.perf_counter()
        findings: list[ReviewFinding] = []
        file_path = _first_changed_path(request)
        line = _line_for_first_file(request)
        harness_contract, knowledge_card_id = _harness_card_contract(messages)

        # 경로에 따라 다른 성격의 지적을 하나 만든다.
        if route.name == "simple_failure_review":
            # 실패 경로: 실패한 체크만 골라 원인 요약을 만든다.
            failed_checks = [check for check in request.checks if check.is_failed]
            summary_text = "하나 이상의 체크가 실패했습니다. 병합 전에 실패 로그를 확인해야 합니다."
            if failed_checks:
                summary_text = (
                    f"{failed_checks[0].kind} 체크가 실패했습니다: "
                    f"{failed_checks[0].summary[:160]}"
                )
            findings.append(
                ReviewFinding(
                    severity="high",
                    category="failure",
                    file_path=file_path,
                    line_start=line,
                    line_end=line,
                    message="PR 체크가 실패해 현재 변경을 정상적으로 검증할 수 없습니다.",
                    suggestion="실패한 체크 로그를 열고 오류와 연결된 변경 파일부터 수정합니다.",
                    evidence={"failed_checks": [check.kind for check in failed_checks]},
                    knowledge_card_id=knowledge_card_id,
                    confidence=0.88,
                )
            )
            risk = "high"
        elif route.name == "deep_quality_review":
            # 심층 경로: 아키텍처/운영 영향 관점의 지적을 만든다.
            risk = "high"
            findings.append(
                ReviewFinding(
                    severity="high",
                    category="architecture",
                    file_path=file_path,
                    line_start=line,
                    line_end=line,
                    message="변경 범위가 크거나 운영 영향이 있는 코드 경로를 수정했습니다.",
                    suggestion=(
                        "권한, 데이터 일관성, 롤백 동작과 운영 관측성을 중심으로 "
                        "추가 사람 리뷰를 수행합니다."
                    ),
                    evidence={"route_reasons": route.reasons},
                    policy_source=policies[0].source_path if policies else None,
                    knowledge_card_id=knowledge_card_id,
                    confidence=0.78,
                )
            )
        else:
            # 표준 경로: 정책이 있으면 정책 기반 지적, 없으면 일반 안내를 만든다.
            risk = "medium" if policies else "low"
            if policies:
                policy = policies[0]
                findings.append(
                    ReviewFinding(
                        severity="medium",
                        category=policy.policy_type,
                        file_path=file_path,
                        line_start=line,
                        line_end=line,
                        message="저장소 정책과 직접 관련된 변경이 포함되어 있습니다.",
                        suggestion=(
                            "변경 코드를 참고 정책과 비교하고 불일치하는 테스트나 API 동작을 "
                            "정책에 맞게 수정합니다."
                        ),
                        evidence={
                            "section_title": policy.section_title,
                            "policy_score": policy.score,
                        },
                        policy_source=f"{policy.source_path}#{policy.section_title}",
                        knowledge_card_id=knowledge_card_id,
                        confidence=0.74,
                    )
                )
            else:
                findings.append(
                    ReviewFinding(
                        severity="low",
                        category="style",
                        file_path=file_path,
                        line_start=line,
                        line_end=line,
                        message="저장소 정책이 없어 일반 변경 정보만 검토했습니다.",
                        suggestion="구체적인 기준이 필요하면 POLICY_ROOT에 저장소 정책을 추가합니다.",
                        knowledge_card_id=knowledge_card_id,
                        confidence=0.62,
                    )
                )

        # 카드 규칙: 하네스는 있는데 붙일 card_id가 없으면 지적을 내지 않는다.
        if harness_contract and not knowledge_card_id:
            findings = []

        model = self.settings.model_for_tier(route.model_tier)
        reasoning_effort = self.settings.reasoning_effort_for_tier(route.model_tier)
        latency_ms = int((time.perf_counter() - start) * 1000)
        usage = ModelCallUsage(
            provider="mock",
            model=model,
            # 실제 토큰 대신, 글자 수를 대략 4로 나눠 토큰 수를 어림한다.
            prompt_tokens=sum(len(message["content"]) for message in messages) // 4,
            completion_tokens=250,
            latency_ms=latency_ms,
            reasoning_effort=reasoning_effort,
        )
        summary = ReviewSummary(
            route_name=route.name,
            model_tier=route.model_tier,
            overall_risk=risk,
            short_comment=(
                summary_text
                if route.name == "simple_failure_review"
                else f"변경 파일 {len(request.changed_files)}개를 검토했습니다."
            ),
            change_summary=_fallback_change_summary(request),
            file_summaries=_file_summaries_from_payload([], request),
        )
        return summary, findings, usage


class LiteLLMClient:
    """실제 Solar3 모델을 호출하는 클라이언트(litellm 라이브러리 사용).

    프롬프트를 보내 JSON 응답을 받고, 빈/깨진 응답은 재시도하며, 결과를 도메인
    객체로 파싱한다. 원하면 Langfuse로 호출 내역을 추적한다.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._langfuse_ready = False  # Langfuse 연동을 이미 켰는지 여부.
        # Lock = 여러 스레드가 동시에 초기화하지 못하게 막는 자물쇠.
        self._langfuse_lock = threading.Lock()

    def _ensure_langfuse_callback(self) -> None:
        """Langfuse 관측 연동을 (아직 안 켰다면) 한 번만 켠다.

        키가 없으면 그냥 건너뛴다. 여러 스레드가 동시에 호출해도 한 번만
        설정되도록 자물쇠로 보호한다(더블 체크: 잠그기 전과 후 모두 확인).
        """
        if (
            self._langfuse_ready
            or not self.settings.langfuse_public_key
            or not self.settings.langfuse_secret_key
        ):
            return
        # with ... : 블록에 들어갈 때 자물쇠를 잠그고, 나올 때 자동으로 푼다.
        with self._langfuse_lock:
            if self._langfuse_ready:
                return
            import litellm

            # litellm은 이 환경변수들로 Langfuse에 접속하므로 여기서 채워 준다.
            os.environ["LANGFUSE_PUBLIC_KEY"] = self.settings.langfuse_public_key
            os.environ["LANGFUSE_SECRET_KEY"] = self.settings.langfuse_secret_key
            os.environ["LANGFUSE_HOST"] = self.settings.langfuse_host
            # 성공/실패 호출 모두 Langfuse로 보내도록 콜백에 등록(중복 등록 방지).
            if "langfuse" not in litellm.success_callback:
                litellm.success_callback.append("langfuse")
            if "langfuse" not in litellm.failure_callback:
                litellm.failure_callback.append("langfuse")
            self._langfuse_ready = True

    def generate_review(
        self,
        request: ReviewRequest,
        route: ReviewRoute,
        policies: list[PolicyChunk],
        messages: list[dict[str, str]],
        review_run_id: str | None = None,
        batch_index: int = 1,
        batch_count: int = 1,
    ) -> tuple[ReviewSummary, list[ReviewFinding], ModelCallUsage]:
        """실제 모델을 호출해 리뷰를 만든다. 응답을 파싱해 도메인 객체로 돌려준다."""
        try:
            from litellm import completion
        except ModuleNotFoundError as exc:
            # litellm 미설치 시, 원인을 명확히 알리며 멈춘다(from exc로 원인 연결).
            raise RuntimeError("litellm is not installed. Run `pip install -e .`.") from exc

        self._ensure_langfuse_callback()

        start = time.perf_counter()
        # route가 정한 tier를 실제 모델 이름/추론 강도/최대 토큰으로 변환한다.
        model = self.settings.model_for_tier(route.model_tier)
        litellm_model = _litellm_model_id(model, self.settings.upstage_api_base_url)
        reasoning_effort = self.settings.reasoning_effort_for_tier(route.model_tier)
        max_tokens = self.settings.max_tokens_for_tier(route.model_tier)
        # completion(...)에 넘길 인자 묶음. **completion_kwargs 로 한 번에 펼쳐 넣는다.
        completion_kwargs: dict[str, Any] = {
            "model": litellm_model,
            "messages": messages,
            "api_key": self.settings.upstage_api_key,
            "api_base": self.settings.upstage_api_base_url,
            "temperature": 0.1,  # 낮을수록 답이 일관적(무작위성 줄임).
            "response_format": {"type": "json_object"},  # 반드시 JSON으로 답하게 강제.
            "max_tokens": max_tokens,
            "timeout": 90,  # 90초 안에 응답 없으면 실패 처리.
            "num_retries": 1,  # litellm 자체 전송 재시도 횟수.
            "metadata": {
                "review_run_id": review_run_id,
                "route_name": route.name,
                "model_tier": route.model_tier,
                "repository": request.repository.full_name,
                "pull_request_number": request.pull_request.number,
                "batch_index": batch_index,
                "batch_count": batch_count,
                "max_tokens": max_tokens,
            },
        }
        # 추론 강도가 설정된 경우에만 해당 파라미터를 추가한다.
        if reasoning_effort:
            completion_kwargs["reasoning_effort"] = reasoning_effort
            completion_kwargs["allowed_openai_params"] = ["reasoning_effort"]
        response = None
        parsed: dict[str, Any] | None = None
        # 응답이 비었거나 JSON이 깨졌을 때를 대비해 최대 2번(range(1,3)) 시도한다.
        for response_attempt in range(1, 3):
            # 기존 인자를 펼치고(**) 이번 시도 번호만 metadata에 덮어써 넣는다.
            attempt_kwargs = {
                **completion_kwargs,
                "metadata": {
                    **completion_kwargs["metadata"],
                    "response_attempt": response_attempt,
                },
            }
            response = completion(**attempt_kwargs)
            content = response.choices[0].message.content
            try:
                # 응답 내용이 비어 있으면(잘린 응답 등) 예외를 내 재시도로 넘긴다.
                if not content or not content.strip():
                    # getattr(obj, 이름, 기본값): 속성이 없어도 안전하게 읽는다.
                    finish_reason = getattr(response.choices[0], "finish_reason", "unknown")
                    usage_payload = getattr(response, "usage", None)
                    completion_tokens = int(
                        getattr(usage_payload, "completion_tokens", 0) or 0
                    )
                    raise RuntimeError(
                        "LLM response content was empty "
                        f"(finish_reason={finish_reason}, "
                        f"completion_tokens={completion_tokens})"
                    )
                parsed = _parse_json(content)
                break  # 정상 파싱하면 반복 종료.
            except RuntimeError:
                # 마지막(2번째) 시도까지 실패하면 예외를 그대로 올린다.
                if response_attempt == 2:
                    raise
        if response is None or parsed is None:  # pragma: no cover - loop contract guard
            raise RuntimeError("LLM response retry did not produce a result")
        latency_ms = int((time.perf_counter() - start) * 1000)

        # 파싱된 JSON에서 summary/findings를 꺼내되, 형태가 이상하면 방어적으로 보정한다.
        summary_payload = parsed.get("summary", {})
        if not isinstance(summary_payload, dict):
            summary_payload = {}
        findings_payload = parsed.get("findings", [])
        file_summaries = _file_summaries_from_payload(
            summary_payload.get("file_summaries"),
            request,
        )
        # 요약이 비었거나 한국어가 아니면 short_comment → 기본 요약 순으로 대체한다.
        change_summary = _korean_text(summary_payload.get("change_summary"))
        if not change_summary:
            change_summary = _korean_text(summary_payload.get("short_comment"))
        if not change_summary:
            change_summary = _fallback_change_summary(request)
        short_comment = _korean_text(summary_payload.get("short_comment")) or change_summary
        summary = ReviewSummary(
            route_name=route.name,
            model_tier=route.model_tier,
            overall_risk=str(summary_payload.get("overall_risk", "medium")),
            short_comment=short_comment,
            change_summary=change_summary,
            file_summaries=file_summaries,
        )
        # findings 목록의 각 dict 항목을 ReviewFinding 객체로 변환한다.
        findings = [
            _finding_from_payload(item)
            for item in findings_payload
            if isinstance(item, dict)
        ]
        # 모델이 알려준 실제 토큰 사용량을 기록한다(과금/관측용).
        usage_payload = getattr(response, "usage", None)
        usage = ModelCallUsage(
            provider="upstage",
            model=model,
            prompt_tokens=int(getattr(usage_payload, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage_payload, "completion_tokens", 0) or 0),
            latency_ms=latency_ms,
            reasoning_effort=reasoning_effort,
            batch_count=1,
        )
        return summary, findings, usage


def _litellm_model_id(model: str, api_base: str | None) -> str:
    """litellm이 요구하는 형식의 모델 식별자를 만든다.

    litellm은 "제공자/모델" 형식을 기대한다. 이미 "/"가 있으면 그대로 쓰고,
    별도 api_base(Upstage 등 OpenAI 호환 서버)가 있으면 "openai/모델"로 붙인다.
    """
    if "/" in model:
        return model
    if api_base:
        return f"openai/{model}"
    return model


def _parse_json(content: str | None) -> dict[str, Any]:
    """모델 응답 문자열을 JSON 객체(dict)로 파싱한다.

    모델이 JSON 앞뒤에 설명 문장을 붙이는 경우가 있어, 통째 파싱이 실패하면
    첫 '{'부터 마지막 '}'까지를 잘라 한 번 더 시도한다.
    """
    if not content or not content.strip():
        raise RuntimeError("LLM response did not contain JSON content")

    try:
        parsed = json.loads(content)  # json.loads: JSON 문자열 → 파이썬 객체.
    except json.JSONDecodeError as exc:
        # 순수 JSON이 아니면, 중괄호로 감싼 객체 부분만 잘라 다시 파싱한다.
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise RuntimeError("LLM response did not contain a JSON object") from exc
        try:
            parsed = json.loads(content[start : end + 1])
        except json.JSONDecodeError as nested_exc:
            raise RuntimeError("LLM response contained an invalid JSON object") from nested_exc

    if not isinstance(parsed, dict):
        raise RuntimeError("LLM response JSON must be an object")
    return parsed


def _finding_from_payload(payload: dict[str, Any]) -> ReviewFinding:
    """모델이 준 dict 하나를 ReviewFinding 객체로 안전하게 변환한다.

    각 필드에 기본값을 두고 타입을 강제해, 값이 빠지거나 형식이 틀려도 죽지 않게 한다.
    """

    # 함수 안에 정의한 도우미(내부 함수). 줄 번호를 정수로 바꾸되 실패하면 None.
    def _maybe_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    return ReviewFinding(
        severity=str(payload.get("severity", "medium")),
        category=str(payload.get("category", "general")),
        file_path=str(payload.get("file_path", "unknown")),
        line_start=_maybe_int(payload.get("line_start")),
        line_end=_maybe_int(payload.get("line_end")),
        message=str(payload.get("message", "")),
        suggestion=str(payload.get("suggestion", "")),
        evidence=payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {},
        policy_source=payload.get("policy_source"),
        knowledge_card_id=payload.get("knowledge_card_id"),
        confidence=float(payload.get("confidence", 0.7) or 0.7),
    )


def create_llm_client(settings: Settings) -> LLMClient:
    """설정(llm_mode)에 따라 실제/가짜 클라이언트 중 하나를 골라 만든다(팩토리)."""
    if settings.llm_mode == "litellm":
        return LiteLLMClient(settings)
    return MockLLMClient(settings)
