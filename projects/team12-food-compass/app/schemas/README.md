# app/schemas/ — Pydantic 스키마

노드 간 주고받는 구조화 데이터의 형태를 정의합니다. 전부 `schemas.py` 한 파일에 있고, 외부에서는 `from app.schemas import ...`로 import합니다.

| 클래스 | 용도 |
|---|---|
| `ParseQuery` | 1차 라우터 LLM의 구조화 출력 — `intent`(price/knowledge/hybrid/off-topic) + `items`(추출 품목) |
| `ValidateQuery` | 2차 방어 검증 LLM의 구조화 출력 — `is_valid` + `reason` |
| `RawPriceOutput` | KAMIS 시세 1건(dpr1~dpr7) — price_cache 저장 시 직렬화 형태 |
| `JudgePriceOutput` | judge_price 판정 결과 — `status`(비쌈/적정/쌈), `diff_pct`, `month_diff_pct`, 정규화 가격/단위 |
