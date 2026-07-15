"""공개 저장소 리뷰 수집 CLI(명령줄 도구).

실제 수집 로직은 backend.app.evaluation.open_source_reviews에 있고, 이 파일은
그 함수들을 명령줄에서 쓰기 좋게 감싼 얇은 진입점이다. 사용 예:

    python -m scripts.collect_open_source_reviews psf/requests --max-prs 50

지정한 저장소의 PR 리뷰/코멘트를 긁어 JSONL 파일로 저장하고, 요약 통계를 출력한다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.evaluation.open_source_reviews import (
    collect_repository_reviews,
    summarize_records,
    write_jsonl,
)


def main() -> None:
    """명령행 인자를 해석해 수집을 실행하고, JSONL 저장 후 요약을 출력한다."""
    # argparse: 명령행 인자를 정의/파싱해 주는 표준 도구. --help도 자동으로 만들어 준다.
    parser = argparse.ArgumentParser(
        description="Collect public GitHub PR review metadata for offline evaluation."
    )
    # 위치 인자(필수): 어떤 저장소를 수집할지.
    parser.add_argument("repository", help="Public repository in owner/name format")
    # 선택 인자(--로 시작): 값을 안 주면 default가 쓰인다.
    parser.add_argument("--max-prs", type=int, default=25)
    parser.add_argument("--state", choices=["open", "closed", "all"], default="closed")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".local-data/evaluation/open-source-reviews.jsonl"),
    )
    args = parser.parse_args()

    records = collect_repository_reviews(
        args.repository,
        max_prs=max(1, args.max_prs),  # 최소 1개는 받도록 보정.
        state=args.state,
    )
    write_jsonl(args.output, records)
    # **summarize_records(...) : 요약 dict의 키/값을 바깥 dict에 그대로 펼쳐 넣는다(언팩).
    print(json.dumps({"output": str(args.output), **summarize_records(records)}, indent=2))


# 직접 실행할 때만 main()을 돈다(import 시에는 실행 안 됨).
if __name__ == "__main__":
    main()
