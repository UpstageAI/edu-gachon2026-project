"""환경설정 — Solar/LLM 키·모델·타임아웃. 키가 없으면 USE_LLM=False → Mock 규칙으로 폴백."""

try:
    from dotenv import load_dotenv
    load_dotenv()   # 프로젝트 루트의 .env 자동 로드
except ImportError:
    pass

import os

# SOLAR_API_KEY 우선, 없으면 UPSTAGE_API_KEY 도 허용
SOLAR_API_KEY = os.getenv("SOLAR_API_KEY") or os.getenv("UPSTAGE_API_KEY") or ""
SOLAR_MODEL = os.getenv("SOLAR_MODEL", "solar-pro2")
SOLAR_BASE_URL = os.getenv("SOLAR_BASE_URL", "https://api.upstage.ai/v1/solar")
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "")          # 예: "gemini/gemini-2.0-flash"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "30"))          # 무한 대기 방지
LLM_NUM_RETRIES = int(os.getenv("LLM_NUM_RETRIES", "2"))   # 일시적 오류 재시도

USE_LLM = bool(SOLAR_API_KEY)   # 키가 있으면 실제 Solar, 없으면 Mock

# Langfuse — LLM 호출 트레이싱(LLMOps 운영 안정성 개선). 키 없으면 비활성.
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
LANGFUSE_ENABLED = bool(LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY)

# --- Supabase ---
# URL 끝의 슬래시는 제거(클라이언트가 이중 슬래시를 싫어함)
SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or ""                    # publishable(anon) — users/attempts REST 클라이언트(app/db)용
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY") or ""    # service_role — 서버 전용, RLS 우회
# 백엔드는 신뢰된 서버이므로 service key를 우선 사용(없으면 publishable로 폴백)
SUPABASE_BACKEND_KEY = SUPABASE_SERVICE_KEY or SUPABASE_KEY
# users/attempts(프로필·숙련도) 기능 활성 조건 — app/db/supabase_client.py가 사용
SUPABASE_ENABLED = bool(SUPABASE_URL and SUPABASE_KEY)
# problems/progress(문제은행·힌트사용량) 기능 활성 조건 — app/repositories/supabase_client.py가 사용
USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_BACKEND_KEY)
