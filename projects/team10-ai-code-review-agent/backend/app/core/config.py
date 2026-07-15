"""애플리케이션 설정(Settings): 환경변수를 읽어 프로그램 동작을 결정하는 곳.

이 프로그램은 코드에 값을 박아 넣는 대신, 실행 환경의 환경변수(예: API 키,
모드, 경로)에서 설정을 읽어 온다. 그래야 로컬/운영 등 환경마다 코드를 고치지
않고 동작을 바꿀 수 있다.

핵심:
- Settings : 모든 설정을 담는 불변 데이터 상자(dataclass).
- Settings.from_env() : 실제로 환경변수를 읽어 Settings를 만드는 진입점.
- model_for_tier / reasoning_effort_for_tier / max_tokens_for_tier :
  라우팅에서 정한 tier(solar3-low/medium/high)를 실제 모델 이름, 추론 강도,
  최대 토큰 수로 바꿔 주는 도우미. tier가 높을수록 더 깊게 추론하고 더 많은
  토큰을 쓴다(비용도 커진다).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _positive_int_env(name: str, default: int) -> int:
    """환경변수를 "양의 정수"로 읽는다. 없으면 기본값, 형식이 틀리면 예외를 낸다.

    os.getenv(name)은 환경변수 값을 문자열로 돌려주고, 없으면 None을 준다.
    토큰 수처럼 반드시 1 이상이어야 하는 설정을 안전하게 읽기 위한 도우미다.
    """
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        # 숫자가 아닌 값이 들어오면 조용히 넘기지 않고 원인을 알리며 멈춘다.
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True)
class Settings:
    """프로그램 전체가 공유하는 설정 값 모음(한 번 만들면 못 바꾸는 불변 상자).

    각 필드의 "= 값"은 환경변수가 없을 때 쓰는 기본값이다. str | None 타입은
    "문자열이거나, 설정 안 됐으면 None"을 뜻한다.
    """

    app_env: str = "local"  # 실행 환경 이름(local/prod 등).
    api_token: str | None = None  # 내부 API 인증 토큰.
    llm_mode: str = "mock"  # "mock"(가짜 리뷰어) 또는 "litellm"(실제 모델 호출).
    publish_mode: str = "local"  # 리뷰 결과 게시 위치(local 파일 vs GitHub).
    storage_backend: str = "local"  # 결과 저장소(local 파일 vs postgres).
    rag_backend: str = "local"  # 정책 검색 백엔드.
    database_url: str | None = None
    upstage_api_key: str | None = None  # Solar 모델 호출용 API 키.
    github_token: str | None = None
    github_webhook_secret: str | None = None  # webhook 서명 검증용 비밀키.
    github_app_id: str | None = None
    github_app_private_key: str | None = None  # GitHub App 개인 키(문자열).
    github_app_private_key_path: Path | None = None  # 개인 키 파일 경로.
    github_api_base_url: str = "https://api.github.com"
    github_webhook_review_mode: str = "after_checks"  # 언제 리뷰를 시작할지.
    github_check_run_name: str = "AI Code Review"  # GitHub Checks에 뜰 이름.
    policy_root: Path = Path("policies")  # 저장소 정책 문서가 있는 폴더.
    local_data_dir: Path = Path(".local-data")
    review_store_path: Path = Path(".local-data/reviews.json")
    comment_output_dir: Path = Path(".local-data/comments")
    upstage_api_base_url: str = "https://api.upstage.ai/v1"
    solar3_model: str = "solar-pro3"  # 실제 호출할 모델 이름.
    # tier별 추론 강도(reasoning effort). 높을수록 더 깊게 생각하지만 느리고 비싸다.
    solar3_low_reasoning_effort: str = "low"
    solar3_medium_reasoning_effort: str = "medium"
    solar3_high_reasoning_effort: str = "high"
    # tier별 응답 최대 토큰 수(답변 길이 상한).
    solar3_low_max_tokens: int = 4096
    solar3_medium_max_tokens: int = 8192
    solar3_high_max_tokens: int = 16384
    review_harness_root: Path = Path("review_harness")  # 검토 절차(skill) 문서 폴더.
    # Langfuse(모델 호출 관측/추적 서비스) 연동 정보. 없으면 연동을 건너뛴다.
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    @classmethod
    def from_env(cls) -> "Settings":
        """환경변수에서 값을 읽어 Settings를 만든다(프로그램 시작 시 한 번 호출).

        @classmethod라서 인스턴스 없이 Settings.from_env()로 부르며, cls는
        Settings 클래스 자신을 가리킨다. os.getenv(이름, 기본값)으로 각 값을
        읽고, 없으면 기본값을 쓴다.
        """
        local_data_dir = Path(os.getenv("LOCAL_DATA_DIR", ".local-data"))
        return cls(
            app_env=os.getenv("APP_ENV", "local"),
            api_token=os.getenv("AI_REVIEWER_TOKEN") or None,
            llm_mode=os.getenv("LLM_MODE", "mock").lower(),
            publish_mode=os.getenv("PUBLISH_MODE", "local").lower(),
            # "값 or None" = 빈 문자열이면 None으로 취급(미설정과 동일하게).
            database_url=os.getenv("DATABASE_URL") or None,
            # 백엔드를 지정 안 했으면, DB 주소가 있으면 postgres, 없으면 local로 자동 결정.
            storage_backend=os.getenv("STORAGE_BACKEND", "").lower()
            or ("postgres" if os.getenv("DATABASE_URL") else "local"),
            rag_backend=os.getenv("RAG_BACKEND", "").lower()
            or ("postgres" if os.getenv("DATABASE_URL") else "local"),
            upstage_api_key=os.getenv("UPSTAGE_API_KEY") or None,
            github_token=os.getenv("GITHUB_TOKEN") or None,
            github_webhook_secret=os.getenv("GITHUB_WEBHOOK_SECRET") or None,
            github_app_id=os.getenv("GITHUB_APP_ID") or None,
            github_app_private_key=os.getenv("GITHUB_APP_PRIVATE_KEY") or None,
            # 경로가 설정돼 있을 때만 Path로 감싸고, 아니면 None.
            github_app_private_key_path=(
                Path(os.environ["GITHUB_APP_PRIVATE_KEY_PATH"])
                if os.getenv("GITHUB_APP_PRIVATE_KEY_PATH")
                else None
            ),
            github_api_base_url=os.getenv("GITHUB_API_BASE_URL", "https://api.github.com"),
            github_webhook_review_mode=os.getenv(
                "GITHUB_WEBHOOK_REVIEW_MODE",
                "after_checks",
            ).lower(),
            github_check_run_name=os.getenv("GITHUB_CHECK_RUN_NAME", "AI Code Review"),
            policy_root=Path(os.getenv("POLICY_ROOT", "policies")),
            local_data_dir=local_data_dir,
            review_store_path=Path(
                os.getenv("REVIEW_STORE_PATH", str(local_data_dir / "reviews.json"))
            ),
            comment_output_dir=Path(
                os.getenv("COMMENT_OUTPUT_DIR", str(local_data_dir / "comments"))
            ),
            upstage_api_base_url=os.getenv("UPSTAGE_API_BASE_URL", "https://api.upstage.ai/v1"),
            solar3_model=os.getenv("SOLAR3_MODEL", "solar-pro3"),
            solar3_low_reasoning_effort=os.getenv("SOLAR3_LOW_REASONING_EFFORT", "low"),
            # 과거에 오타(MIDIUM)로 쓰던 환경변수도 하위 호환으로 함께 인정한다.
            solar3_medium_reasoning_effort=(
                os.getenv("SOLAR3_MEDIUM_REASONING_EFFORT")
                or os.getenv("SOLAR3_MIDIUM_REASONING_EFFORT")
                or "medium"
            ),
            solar3_high_reasoning_effort=os.getenv("SOLAR3_HIGH_REASONING_EFFORT", "high"),
            solar3_low_max_tokens=_positive_int_env("SOLAR3_LOW_MAX_TOKENS", 4096),
            solar3_medium_max_tokens=_positive_int_env("SOLAR3_MEDIUM_MAX_TOKENS", 8192),
            solar3_high_max_tokens=_positive_int_env("SOLAR3_HIGH_MAX_TOKENS", 16384),
            review_harness_root=Path(os.getenv("REVIEW_HARNESS_ROOT", "review_harness")),
            langfuse_public_key=os.getenv("LANGFUSE_PUBLIC_KEY") or None,
            langfuse_secret_key=os.getenv("LANGFUSE_SECRET_KEY") or None,
            langfuse_host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )

    def model_for_tier(self, model_tier: str) -> str:
        """tier 이름(solar3-low 등)을 실제 모델 이름으로 바꾼다.

        지금은 모든 solar3-* tier가 같은 모델(solar3_model)을 쓰되, 아래
        reasoning effort/토큰 설정으로만 강도를 조절한다. solar3-로 시작하지
        않는 값은 그대로 모델 이름으로 취급한다.
        """
        if model_tier.startswith("solar3-"):
            return self.solar3_model
        return model_tier

    def reasoning_effort_for_tier(self, model_tier: str) -> str:
        """tier에 맞는 추론 강도를 돌려준다. 알 수 없는 tier면 medium을 쓴다."""
        if model_tier == "solar3-low":
            return self.solar3_low_reasoning_effort
        if model_tier == "solar3-medium":
            return self.solar3_medium_reasoning_effort
        if model_tier == "solar3-high":
            return self.solar3_high_reasoning_effort
        return self.solar3_medium_reasoning_effort

    def max_tokens_for_tier(self, model_tier: str) -> int:
        """tier에 맞는 응답 최대 토큰 수를 돌려준다. 기본은 medium 값."""
        if model_tier == "solar3-low":
            return self.solar3_low_max_tokens
        if model_tier == "solar3-high":
            return self.solar3_high_max_tokens
        return self.solar3_medium_max_tokens
