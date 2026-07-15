# ---- Stage 1: 빌드 (의존성 설치) ----
FROM python:3.11-slim AS builder

WORKDIR /build

COPY requirements.txt .

# psycopg2-binary 빌드에 필요한 최소 시스템 패키지
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ---- Stage 2: 런타임 (실제 실행 이미지, 훨씬 가벼움) ----
FROM python:3.11-slim

WORKDIR /app

# 빌드 스테이지에서 설치된 패키지만 복사 (컴파일러 등 빌드 도구는 최종 이미지에 안 남음)
COPY --from=builder /install /usr/local

# 런타임에 실제로 필요한 코드만 복사
# (raw_data/processed_data/tests/.github 등은 .dockerignore로 이미 제외됨)
COPY app/ ./app/
COPY tools/ ./tools/
COPY preprocessors/ ./preprocessors/

ENV PYTHONUNBUFFERED=1
ENV PORT=8080

EXPOSE 8080

# non-root 유저로 실행 (보안 기본 관행)
RUN useradd -m appuser
USER appuser

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]