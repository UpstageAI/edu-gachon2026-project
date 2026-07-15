# app/prompts/ — LLM 프롬프트 중앙 관리

프로젝트의 모든 프롬프트를 `prompts.py` 한 파일에서 상수로 관리합니다. 새 프롬프트를 추가할 때도 여기에 정의하세요.

## prompts.py 구성

| 상수 | 용도 |
|---|---|
| `ROUTER_SYSTEM_PROMPT` | 1차 라우터 — 4분류(price/knowledge/hybrid/off-topic) + 품목 추출 (JSON 구조화 출력 강제, few-shot 예시 포함) |
| `VALIDATION_SYSTEM_PROMPT` | 2차 방어 — 1차 분류 결과가 진짜 가격/지식 질문인지 재검증 (장난·대사체 문장 차단, 품목명의 낯섦은 판단 기준 아님) |
| `COMMON_ANSWER_SYSTEM_PROMPT` | **답변 생성 4개 노드 공통** — 페르소나(또래 친구 어조), 데이터 조작 금지, 품목명 필수 언급, 조언형 어투, 이모지 최대 2개, 마크다운 금지 |
| `ANSWER_GENERATION_SYSTEM_PROMPT` | judge_price 전용 — 판정(status) 그대로 따르기, 필수 시작 문장 사용, 평년가는 참고 정보로만 |
| `COMPARISON_ANSWER_SYSTEM_PROMPT` | 시나리오 1(쌀 vs 즉석밥) 전용 — 환산 기준 공시, 결론 먼저 |
| `PROCESSED_PRICE_ANSWER_SYSTEM_PROMPT` | 가공식품 조회 전용 — 판정 금지, 매칭 상품 전부 나열 |
| `KNOWLEDGE_GENERATION_SYSTEM_PROMPT` | 지식 RAG 전용 — 참고 문서 내용만 사용, 번호 목록 형식 |
| `ANSWER_*_LINE`, `KNOWLEDGE_*`, `OFFTOPIC_RESPONSE` 등 | LLM 실패/데이터 없음 시 쓰는 고정 템플릿 문구 |

## 프롬프트 전달 방식

답변 생성 노드들은 `COMMON_ANSWER_SYSTEM_PROMPT`(공통 원칙)와 노드별 프롬프트(고유 규칙)를 **각각 별도의 SystemMessage**로 함께 LLM에 전달합니다(`app/graph/nodes.py`의 `_invoke_with_prompts`). 공통 규칙은 한 곳에서만 수정하면 4개 노드에 모두 반영됩니다.
