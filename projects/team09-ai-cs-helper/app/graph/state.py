import time
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class InquiryState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

    # 외부 임베딩/LLM 서비스에 전달할 개인정보 마스킹 문의
    masked_text: str | None

    # Router 노드에서 결정된 의도
    intent: Literal["to_human", "AI_generate"] | None

    # 타당성 검증 Router 노드에서 결정된 ai답변의 타당성
    answer_review: Literal["pass", "fail"] | None

    # fail 사유. LLM 프롬프트에 추가해서 좋은 결과를 뽑기 위함
    review_feedback: str | None

    retry_count: int  # 초기값 0

    # RAG 노드에서 검색된 문서 (content + metadata 포함)
    retrieved_docs: list[dict]

    # AI가 분류한 카테고리
    categories: str | None

    # AI가 생성한 답변
    ai_answer: str | None

    # 인간이 승인/수정한 최종 답변
    final_answer: str | None

    # 처리 상태
    status: Literal["문의 접수", "답변 생성", "답변 완료", "상담원 확인 필요"]

    # RAG 검색이 오류로 실패했는지 여부. True면 router가 LLM 호출 없이 상담원 이관.
    rag_failed: bool

    # 처리자 (AI 또는 사람)
    reviewer_type: str | None

    # 세션
    session_id: str

    # 전체 파이프라인 소요 시간 계산용 시작 시각(epoch seconds)
    pipeline_started_at: float

    # 문의 식별자 (DB의 inquiry_id와 매칭)
    inquiry_id: str | None


def create_initial_state(
    session_id: str,
    inquiry_id: str | None = None,
    messages: list[BaseMessage] | None = None,
) -> InquiryState:
    """
    초기 상태를 생성합니다.

    Args:
        session_id: 세션 식별자
        inquiry_id: 문의 식별자 (선택)
        messages: 초기 메시지 목록 (선택)

    Returns:
        InquiryState: 초기화된 상태 딕셔너리
    """
    return InquiryState(
        messages=messages or [],
        masked_text=None,
        intent=None,
        rag_failed=False,
        retrieved_docs=[],
        categories=None,
        ai_answer=None,
        final_answer=None,
        status="문의 접수",
        reviewer_type=None,
        answer_review=None,
        review_feedback=None,  # fail 사유 (재생성 시 참고)
        retry_count=0,
        session_id=session_id,
        pipeline_started_at=time.time(),
        inquiry_id=inquiry_id,
    )
