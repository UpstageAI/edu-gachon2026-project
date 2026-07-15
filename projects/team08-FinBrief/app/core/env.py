"""의존성 없이 repo 루트 .env 를 os.environ 로 로드하는 공유 헬퍼.

컨테이너(docker compose env_file)에서는 이미 env 가 주입되므로 setdefault 로
기존 값을 덮어쓰지 않는다. standalone 실행(python -m app.services.batch 등)에서만
.env 를 읽어와 SUPABASE/토큰 등이 os.getenv 로 조회되도록 보장한다.
"""
from __future__ import annotations

import os

_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", "..", ".env")


def load_dotenv(path: str | None = None) -> None:
    """repo 루트 .env 를 os.environ 로 로드(이미 설정된 값은 유지)."""
    try:
        with open(path or _ENV_PATH, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())
    except FileNotFoundError:
        pass
