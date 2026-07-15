# syntax=docker/dockerfile:1
# Healthy Meal Agent — 멀티 스테이지 빌드 (강의 5강 구조를 우리 프로젝트에 맞춤)
# - builder: uv로 의존성만 설치 (.venv 생성)
# - runtime: builder에서 .venv만 복사 + 앱 코드 → 이미지 크기 최소화
# API·UI 공용 이미지. 실행 커맨드(CMD)는 docker-compose에서 서비스별로 덮어쓴다.

# ── Stage 1: builder ──────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# uv 설치 (astral 공식 이미지에서 바이너리만 복사)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 의존성 파일 먼저 복사 (레이어 캐시 활용 — 코드만 바뀌면 재설치 안 함)
# uv sync는 pyproject.toml + uv.lock + README.md(readme 설정)를 참조
COPY pyproject.toml uv.lock README.md ./

# 의존성 설치 (production 모드)
#   --frozen: uv.lock 기준 정확한 버전 고정
#   --no-dev: dev 의존성(pytest·ruff) 제외
#   --no-install-project: 아직 앱 코드가 없으니 프로젝트 자체는 나중에
RUN uv sync --frozen --no-dev --no-install-project

# ── Stage 2: runtime ──────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# 런타임에 필요한 시스템 패키지 (curl: 헬스체크용)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# uv (런타임에서도 uv run 사용)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 빌드 스테이지에서 설치한 의존성(.venv)만 복사
COPY --from=builder /app/.venv /app/.venv

# 애플리케이션 코드 복사
COPY pyproject.toml uv.lock README.md ./
COPY app/ ./app/
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# 보안: non-root 유저 생성 및 권한 설정 (production에서는 절대 root로 실행 안 함)
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

# 환경변수: .venv를 우선 PATH에 (uv run 없이도 실행 가능)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# 포트: API는 8000, UI(streamlit)는 8501 (compose에서 각각 매핑)
EXPOSE 8000 8501

# 기본 CMD는 API 서버 (UI는 compose에서 command로 덮어씀)
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
