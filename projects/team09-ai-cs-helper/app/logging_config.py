"""중앙 로깅 설정.

LOG_LEVEL 환경변수(기본 INFO)로 레벨을 정하고, 콘솔(stderr)로 출력한다.
각 모듈은 `logger = logging.getLogger(__name__)`로 로거를 얻어 사용한다.
"""

import logging
import os

_configured = False

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def setup_logging(level: str | None = None) -> None:
    """로깅을 1회 설정한다. 여러 번 호출해도 핸들러가 중복되지 않는다."""
    global _configured
    if _configured:
        return

    resolved = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    handler = logging.StreamHandler()  # 기본 stderr
    handler.setFormatter(logging.Formatter(LOG_FORMAT))

    root = logging.getLogger()
    root.setLevel(resolved)
    # uvicorn 등이 이미 핸들러를 붙였을 수 있으니 우리 포맷 핸들러가 없을 때만 추가
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        root.addHandler(handler)

    _configured = True
