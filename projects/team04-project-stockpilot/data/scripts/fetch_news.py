"""기업 최신 뉴스 확인용 CLI.

실행:
    uv run python data/scripts/fetch_news.py --company 삼성전자 --days 7
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.repositories.news import get_company_news, get_stock_issue_news  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="기업 최신 뉴스 조회")
    parser.add_argument("--company", required=True)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--direction",
        choices=["down", "up", "neutral"],
        default="neutral",
        help="주가 하락/상승 관련 이슈를 우선 검색",
    )
    return parser.parse_args()


async def main_async() -> None:
    args = parse_args()
    if args.direction == "neutral":
        items = await get_company_news(
            args.company,
            days=args.days,
            limit=args.limit,
        )
    else:
        items = await get_stock_issue_news(
            args.company,
            direction=args.direction,
            days=args.days,
            limit=args.limit,
        )
    serializable = [
        {
            **item,
            "published_at": (
                item["published_at"].isoformat() if item["published_at"] else None
            ),
        }
        for item in items
    ]
    print(json.dumps(serializable, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main_async())
