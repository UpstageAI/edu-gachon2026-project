"""리뷰 파이프라인의 진입점(오케스트레이터).

바깥(API 라우터, GitHub webhook 처리부 등)에서 "이 PR을 리뷰해줘"라고 부르는
가장 바깥쪽 조립 담당이다. 실제 단계별 처리는 review_graph.py의 그래프가 하고,
여기서는 필요한 부품(정책 검색, LLM 클라이언트, 게시기, 저장소, 하네스)을 모아
그래프를 만들어 한 번 실행한다.

- ReviewOrchestrator : 부품들을 들고 있다가 run_review()로 리뷰 한 건을 실행.
- create_orchestrator() : 설정(Settings)만 주면 부품들을 알아서 만들어 오케스트레이터를
  조립해 주는 도우미(팩토리) 함수.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from backend.app.core.config import Settings
from backend.app.core.schemas import JsonDict, ReviewRequest, ReviewResult
from backend.app.services.llm import LLMClient, create_llm_client
from backend.app.services.policy_harness import PolicyHarness
from backend.app.services.publisher import ReviewPublisher, create_publisher
from backend.app.services.rag import LocalPolicyIndex, create_policy_index
from backend.app.services.review_graph import ReviewWorkflowGraph
from backend.app.storage.factory import ReviewStore, create_review_store


class ReviewOrchestrator:
    """리뷰에 필요한 부품들을 들고 있다가, 요청이 오면 그래프를 실행하는 조립체."""

    def __init__(
        self,
        policy_index: LocalPolicyIndex,
        llm_client: LLMClient,
        publisher: ReviewPublisher,
        store: ReviewStore,
        policy_harness: PolicyHarness | None = None,
    ) -> None:
        self.policy_index = policy_index
        self.llm_client = llm_client
        self.publisher = publisher
        self.store = store
        # policy_harness를 안 주면(None) 기본 설정 경로로 하나 만들어 쓴다.
        # (A or B): A가 참 같은 값이면 A를, 아니면 B를 쓰는 관용구.
        self.policy_harness = policy_harness or PolicyHarness(Settings().review_harness_root)

    def run_review(
        self,
        request: ReviewRequest,
        review_run_id: str | None = None,
        event_publisher: Callable[[str, JsonDict | None], object] | None = None,
    ) -> ReviewResult:
        """리뷰 한 건을 처음부터 끝까지 실행하고 최종 결과(ReviewResult)를 돌려준다.

        review_run_id: 이 리뷰 실행을 구분하는 고유 ID. 안 주면 새로 만든다.
        event_publisher: 진행 상황을 실시간(SSE)으로 흘려보낼 콜백 함수(선택).
          Callable[[...], object] = "이런 인자를 받는 함수"라는 타입 힌트.
        """
        # str | None = "문자열이거나 없음". 없으면 uuid4로 랜덤 ID를 새로 만든다.
        resolved_review_run_id = review_run_id or str(uuid.uuid4())

        # 그래프 안에서 이벤트를 발행할 때 쓸 작은 래퍼. event_publisher가 없으면
        # 아무 일도 하지 않아, 호출부가 이벤트 유무를 신경 쓰지 않아도 되게 한다.
        # (함수 안에 정의한 함수 = 바깥 변수 event_publisher를 그대로 참조한다.)
        def publish(event_type: str, payload: JsonDict | None = None) -> None:
            if event_publisher:
                event_publisher(event_type, payload or {})

        try:
            return ReviewWorkflowGraph(
                policy_index=self.policy_index,
                llm_client=self.llm_client,
                publisher=self.publisher,
                store=self.store,
                policy_harness=self.policy_harness,
                event_publisher=publish,
            ).run(
                request=request,
                review_run_id=resolved_review_run_id,
            )
        except Exception as exc:
            # 어느 단계에서든 실패하면 "review_failed" 이벤트로 알린 뒤,
            # raise로 예외를 그대로 다시 던져 호출부가 처리하게 한다(에러를 삼키지 않음).
            publish(
                "review_failed",
                {
                    "error_type": exc.__class__.__name__,
                    "message": str(exc),
                },
            )
            raise


def create_orchestrator(settings: Settings | None = None) -> ReviewOrchestrator:
    """설정만 받아 필요한 부품을 모두 만들어 오케스트레이터를 조립하는 팩토리.

    settings를 안 주면 환경 변수(from_env)에서 읽어 온다. 각 create_* 함수가
    설정에 맞는 구현체(로컬/원격 등)를 골라 만들어 준다.
    """
    resolved_settings = settings or Settings.from_env()
    return ReviewOrchestrator(
        policy_index=create_policy_index(resolved_settings),
        llm_client=create_llm_client(resolved_settings),
        publisher=create_publisher(resolved_settings),
        store=create_review_store(resolved_settings),
        policy_harness=PolicyHarness(resolved_settings.review_harness_root),
    )
