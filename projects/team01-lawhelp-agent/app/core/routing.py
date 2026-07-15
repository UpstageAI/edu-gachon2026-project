from enum import Enum


# 2026-07-15 골든셋 75문항 1차 평가(eval_report_r1.md) 근거로 팀 확정.
# 기대1 top-1 distance 0.32~0.643, 기대3 0.544~0.693으로 분포가 겹쳐,
# 치명 방향(기대3→실제1) 0건을 유지하면서 라우팅 정확도를 최대화하는 조합(52%→71%).
# 상한 0.65는 uncertain 오차단 5건을 해소하고 무관 최소값(0.691)과 0.04 간격 유지.
EXACT_DISTANCE_THRESHOLD = 0.54
RELATED_DISTANCE_THRESHOLD = 0.65


class AnswerRoute(str, Enum):
    OUT_OF_SCOPE = "out_of_scope"
    GROUNDED_RAG = "grounded_rag"
    RELATED_HYBRID = "related_hybrid"
    LLM_ONLY = "llm_only"
    ERROR = "error"


class DomainGuardrailResult(str, Enum):
    IN_SCOPE = "in_scope"
    OUT_OF_SCOPE = "out_of_scope"
    UNCERTAIN = "uncertain"
