"""로컬 실행 진입점(CLI): 서버를 띄우지 않고 명령줄에서 리뷰를 한 번 돌려 본다.

JSON 파일 하나(리뷰 요청)를 받아 파이프라인을 실행하고 결과를 화면에 출력한다.
개발/디버깅이나 오프라인 테스트에 쓴다. 실제 서비스 경로는 main.py의 API다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.core.config import Settings
from backend.app.core.schemas import ReviewRequest
from backend.app.services.orchestrator import create_orchestrator
from backend.app.services.rag import create_policy_index


def main() -> None:
    """명령줄 인자를 읽어 리뷰를 한 번 실행하고 결과 JSON을 출력한다."""
    # argparse = 파이썬 표준 명령줄 인자 파서. "무슨 옵션을 받을지"를 등록한다.
    parser = argparse.ArgumentParser(description="Run a local AI code review.")
    # 위치 인자: 리뷰 요청이 담긴 JSON 파일 경로(type=Path로 자동 변환).
    parser.add_argument("payload", type=Path, help="Path to a review request JSON file.")
    # 선택 플래그: 붙이면(store_true) 정책 색인 통계를 먼저 찍는다.
    parser.add_argument("--sync-policies", action="store_true", help="Print local policy index stats.")
    args = parser.parse_args()

    # 환경 변수에서 설정을 읽어 온다(모델 키, 저장소 경로 등).
    settings = Settings.from_env()
    if args.sync_policies:
        # 정책 문서를 다시 색인하고 그 결과 통계를 보기 좋게 출력한다.
        stats = create_policy_index(settings).sync()
        # ensure_ascii=False = 한글을 \uXXXX로 깨지 않고 그대로 출력한다.
        print(json.dumps(stats, indent=2, ensure_ascii=False))

    # JSON 파일을 읽어 dict로 바꾼 뒤, 도메인 객체(ReviewRequest)로 변환한다.
    payload = json.loads(args.payload.read_text(encoding="utf-8"))
    request = ReviewRequest.from_dict(payload)
    # 오케스트레이터가 라우팅→모델 호출→결과 조립까지 파이프라인 전체를 돌린다.
    result = create_orchestrator(settings).run_review(request)
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))


# 이 파일을 직접 실행할 때(python -m ... / python cli.py)만 main()을 부른다.
# 다른 모듈이 import할 때는 실행되지 않는다.
if __name__ == "__main__":
    main()
