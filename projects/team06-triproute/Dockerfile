# ==============================
# 1단계: 의존성 빌드
# ==============================
FROM python:3.14-slim-trixie AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./

RUN uv sync \
    --frozen \
    --no-dev \
    --no-install-project

# ==============================
# 2단계: 실제 실행 이미지
# ==============================
FROM python:3.14-slim-trixie AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# 애플리케이션 실행용 일반 사용자 생성
RUN addgroup --system appgroup \
    && adduser --system --ingroup appgroup appuser

# 가상환경과 소스 코드를 일반 사용자 소유로 복사
COPY --from=builder --chown=appuser:appgroup /app/.venv /app/.venv
COPY --chown=appuser:appgroup . .

# 이후 명령은 root가 아닌 appuser 권한으로 실행
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]