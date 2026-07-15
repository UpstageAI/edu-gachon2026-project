# syntax=docker/dockerfile:1

FROM python:3.11-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./

# 의존성만 설치하고, 현재 프로젝트 자체는 설치하지 않는다.
# 이렇게 하면 README.md나 app 폴더가 아직 없어도 빌드가 깨지지 않는다.
RUN uv sync --frozen --no-dev --no-install-project


FROM python:3.11-slim AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"

COPY --from=builder /app/.venv /app/.venv

COPY app ./app
COPY output ./output

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
