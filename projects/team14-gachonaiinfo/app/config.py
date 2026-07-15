"""애플리케이션 설정 (.env 로드)."""

import os
import pathlib

from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Upstage (Solar) — OpenAI 호환 엔드포인트
UPSTAGE_API_KEY = os.getenv("UPSTAGE_API_KEY", "")
UPSTAGE_BASE_URL = os.getenv("UPSTAGE_BASE_URL", "https://api.upstage.ai/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "solar-pro3")

# Upstage 임베딩 모델 (solar-embedding-1-large 계열, 4096차원)
EMBED_MODEL_PASSAGE = os.getenv("EMBED_MODEL_PASSAGE", "embedding-passage")
EMBED_MODEL_QUERY = os.getenv("EMBED_MODEL_QUERY", "embedding-query")
EMBED_DIM = int(os.getenv("EMBED_DIM", "4096"))

# PostgreSQL + pgvector
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/gachon_ai")

# Resend 이메일 리마인드 (ADR-007)
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")

# 데이터 경로
STRUCTURED_DIR = ROOT / "output" / "structured"
PARSED_DIR = ROOT / "output" / "parsed"

# 가드레일: RAG 최고 점수가 이 값보다 낮으면 '자료 없음'으로 보고 문의처 안내
# score = reranker 가중합(vector*0.65+keyword*0.15+category*0.10+priority*0.05+recency*0.05).
# 실측: 관련 질문 0.62+, 무관 질문 ≤0.37 → 0.40 으로 분리. (리랭크 도입 전 0.35에서 상향)
# 2026-07-15: 시나리오 50개 평가에서 범위밖 질문(등록금·재수강·전과 등)이 어휘 겹침으로
#   0.40~0.54를 받아 under-fire. 정상질문 최저점 0.469와 겹치지 않는 0.45로 상향
#   (진단: eval/diag_guardrail.py). 임계값 단독 효과(Tier1 N=5): 가드레일 82.5→87.5%,
#   단 스몰토크 S38이 0.404로 걸려 검색 100→95.8% 손상 → nodes.py 라우터 스몰토크
#   단락으로 별도 수정. 임계값+스몰토크 단계: 가드레일 89.7%·검색 100%·intent 98.2%.
#   남은 under-fire 4건(재수강·계절학기등록금·전과·셔틀)은 정상질문(최저 0.469,
#   "수강신청은 어떻게 해?" 0.497)과 점수대가 겹쳐 임계값·벡터점수 단독으론 분리 불가.
#   → nodes.py `_OUT_OF_SCOPE_TOPICS`(자료 미보유 주제 레지스트리)로 점수 무관 가드레일.
#   최종(Tier1 N=3): 가드레일 100%·검색 100%·intent 98.2%.
GUARDRAIL_MIN_SCORE = float(os.getenv("GUARDRAIL_MIN_SCORE", "0.45"))

DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# Langfuse 관측성 (LangGraph trace). key가 비어 있거나 ENABLED=false면 완전히 비활성.
# region별 base_url이 다르고 API key도 region 전용이다(현재 프로젝트는 Japan region).
LANGFUSE_ENABLED = os.getenv("LANGFUSE_ENABLED", "false").lower() == "true"
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_BASE_URL = os.getenv("LANGFUSE_BASE_URL", "https://jp.cloud.langfuse.com")
LANGFUSE_ENV = os.getenv("LANGFUSE_ENV", "local")
