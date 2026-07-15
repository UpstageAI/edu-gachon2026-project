"""Solar 모델 라우팅 벤치마크 설정.

난이도(하/중/상/최상)별로 solar-mini / pro2 / pro3 의 SQL 성공률·토큰·비용을
비교해서, 어느 난이도를 어느 모델로 라우팅할지 결정하기 위한 실험 설정.

가격/모델명은 이 파일만 고치면 된다.
"""
from __future__ import annotations

import os
from pathlib import Path

# ── 경로 ────────────────────────────────────────────────────────────────
BENCH_DIR = Path(__file__).resolve().parent
# AI Hub NL2SQL 원본 zip (repo 밖, 용량 커서 gitignore). 환경변수로 재정의 가능.
DATASET_ROOT = Path(
    os.getenv("NL2SQL_DATASET_ROOT", BENCH_DIR.parents[2] / "148.자연어 기반 질의(NL2SQL) 검색 생성 데이터")
)
VAL_LABEL_ZIP = DATASET_ROOT / "01-1.정식개방데이터/Validation/02.라벨링데이터/VL.zip"
VAL_SOURCE_ZIP = DATASET_ROOT / "01-1.정식개방데이터/Validation/01.원천데이터/VS.zip"

EVAL_SET = BENCH_DIR / "eval_set.json"   # build_eval_set.py 산출물 (기준 표본)
DB_DIR = BENCH_DIR / "dbs"               # 샘플된 db_id 의 sqlite 만 로컬 복사
RESULTS = BENCH_DIR / "results.jsonl"    # (호환) zero-shot 결과

FEWSHOT_K = int(os.getenv("BENCH_FEWSHOT_K", "3"))       # 같은 db_id 예시 개수
SCHEMA_VALUE_K = int(os.getenv("BENCH_VALUE_K", "3"))    # schema-linker 컬럼당 예시 값 개수

# 실험 조건 2×2: {plain|schema-linked 스키마} × {few-shot 유무}
#   zero       : 스키마 DDL만
#   few        : DDL + 같은 db few-shot
#   schema     : DDL + 컬럼별 샘플 값(value_retriever), few-shot 없음
#   schema_few : DDL + 샘플 값 + few-shot
CONDITIONS = {
    "zero":       (EVAL_SET, RESULTS),
    "few":        (BENCH_DIR / "eval_set_fewshot.json", BENCH_DIR / "results_fewshot.jsonl"),
    "schema":     (BENCH_DIR / "eval_set_schema.json", BENCH_DIR / "results_schema.jsonl"),
    "schema_few": (BENCH_DIR / "eval_set_schema_fewshot.json", BENCH_DIR / "results_schema_fewshot.jsonl"),
}
CONDITION_LABELS = {"zero": "zero-shot", "few": "few-shot",
                    "schema": "schema-linker", "schema_few": "schema+few"}
# 하위호환 별칭
EVAL_SET_FEWSHOT, RESULTS_FEWSHOT = CONDITIONS["few"]

# ── 난이도 매핑: AI Hub hardness → 하/중/상/최상 ──────────────────────────
HARDNESS_ORDER = ["easy", "medium", "hard", "extra hard"]
HARDNESS_KO = {"easy": "하", "medium": "중", "hard": "상", "extra hard": "최상"}

SAMPLES_PER_LEVEL = int(os.getenv("BENCH_SAMPLES", "25"))  # 난이도별 문항 수
SEED = 7

# ── 모델 & 가격 (Upstage, USD per 1M tokens) ─────────────────────────────
# 출처: https://www.upstage.ai/pricing/api (2026-07 확인). 캐시 미적용 기준.
UPSTAGE_BASE_URL = os.getenv("UPSTAGE_BASE_URL", "https://api.upstage.ai/v1")
# 키: OpenAI 호환 API 의 model 문자열. pro3 문자열은 계정에서 한번 확인 권장.
MODELS: dict[str, dict[str, float]] = {
    "solar-mini": {"in": 0.15, "out": 0.15},
    "solar-pro2": {"in": 0.15, "out": 0.60},
    "solar-pro3": {"in": 0.15, "out": 0.60},
}

# 라우팅 판정 기준: EX(실행결과 일치) 성공률이 이 값 이상이면 "충분" (기획서 KPI 70%)
ROUTING_EX_TARGET = float(os.getenv("BENCH_EX_TARGET", "0.70"))

# 생성 파라미터
TEMPERATURE = 0.0
MAX_TOKENS = 800
REQUEST_TIMEOUT = 60.0
EXEC_TIMEOUT_S = 5.0  # 생성 SQL 실행 시 폭주 쿼리 차단 (초)


def price_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    p = MODELS[model]
    return (prompt_tokens * p["in"] + completion_tokens * p["out"]) / 1_000_000
