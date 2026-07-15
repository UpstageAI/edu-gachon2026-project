# syntax=docker/dockerfile:1.7

# --- Build Stage ---
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /app
# 캐시 효율을 높이기 위해 환경 변수 세팅
ENV UV_LINK_MODE=copy
ENV UV_COMPILE_BYTECODE=1
# 의존성 파일 먼저 복사
COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- Runtime Stage ---
FROM python:3.12-slim-bookworm AS runner

WORKDIR /app

ENV PYTHONUNBUFFERED=1
# 최종 컨테이너 환경 변수에 가상환경 경로를 추가하여 파이썬이 바로 인식하게 함
ENV PATH="/app/.venv/bin:$PATH"

# 빌더 스테이지에서 생성된 가상환경(.venv)만 빼오기
COPY --from=builder /app/.venv /app/.venv

# 실제 애플리케이션 소스 코드 복사
COPY app ./app
COPY scripts ./scripts

EXPOSE 8000

# 이미 PATH에 가상환경이 잡혀있으므로 바로 uvicorn 실행 가능
CMD ["sh", "-c", "uvicorn app.main:app --host ${BACKEND_HOST:-0.0.0.0} --port ${BACKEND_PORT:-8000}"]




# 원본
# syntax=docker/dockerfile:1.7

#FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

#WORKDIR /app

#ENV UV_LINK_MODE=copy
#ENV PYTHONUNBUFFERED=1

#COPY pyproject.toml uv.lock ./
#RUN --mount=type=cache,target=/root/.cache/uv \
#    uv pip install --system fastapi python-dotenv uvicorn

#COPY app ./app

#EXPOSE 8000

#CMD ["sh", "-c", "python -m uvicorn app.main:app --host ${BACKEND_HOST:-0.0.0.0} --port ${BACKEND_PORT:-8000}"]