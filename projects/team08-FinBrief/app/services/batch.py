"""아침 배치 러너 — 구독 기반 카드 생성 + 발송(전체 파이프라인 1회 실행).

실행:  python -m app.services.batch            # DELIVERY_DRY_RUN 환경값 그대로
       python -m app.services.batch --dry-run  # 발송 없이 상태만(테스트)

live 데이터(실 지표/RAG 뉴스)는 ENABLE_MOCK_DATA=false 일 때 켜진다(pipeline 규약).
실 발송은 DELIVERY_DRY_RUN=false + DISCORD_BOT_TOKEN 필요.
"""
from __future__ import annotations

import argparse
import os
from datetime import date, datetime, timedelta, timezone

from app.agents.pipeline import run_morning_pipeline
from app.core.env import load_dotenv
from app.core.schemas import BatchRunResult

# 아침 브리핑은 KST 기준. 컨테이너는 UTC 라 date.today() 를 쓰면 07:00 KST(=전날 22:00 UTC)에
# 하루 밀린 날짜가 잡힌다 → run_date 를 KST 날짜로 계산.
KST = timezone(timedelta(hours=9))

# standalone 실행 시 .env 로드(토큰/DB 키가 os.getenv 로 조회되도록).
# 컨테이너는 env_file 로 이미 주입되어 setdefault 로 무시된다.
load_dotenv()


def run_batch(
    *,
    run_date: date | None = None,
    send_report: bool = True,
    send_cards: bool = True,
    only_user: str | None = None,
) -> BatchRunResult:
    """전체시장 리포트 + 구독 토픽 카드 생성/발송을 1회 실행."""
    # 실 repo + RAG 쿼리 임베딩 provider (뉴스 match_news 에 필요)
    from app.repositories.supabase import create_supabase_repositories
    from app.tools.embedding.upstage import UpstageEmbeddingProvider

    run_date = run_date or datetime.now(KST).date()
    repos = create_supabase_repositories(
        query_embedding_provider=UpstageEmbeddingProvider().embed_query
    )
    from app.services import notifier

    return run_morning_pipeline(
        repos,
        run_date=run_date,
        run_id=f"batch_{run_date:%Y%m%d}",
        dry_run=notifier.dry_run(),
        send_report=send_report,
        send_cards=send_cards,
        only_user=only_user,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="FinBrief 아침 배치 실행")
    parser.add_argument("--dry-run", action="store_true", help="발송 없이 상태만(DELIVERY_DRY_RUN=true 강제)")
    parser.add_argument("--mock", action="store_true", help="목업/fixture 데이터로 실행(ENABLE_MOCK_DATA=true)")
    parser.add_argument("--images", action="store_true", help="카드 이미지 실제 생성(FINBRIEF_IMAGE_STUB=0, Gemini 과금)")
    parser.add_argument("--no-report", action="store_true", help="지표 리포트 발송 안 함")
    parser.add_argument("--no-cards", action="store_true", help="카드뉴스 발송 안 함(리포트만 테스트)")
    parser.add_argument("--only-user", default="", help="특정 계정만(디스코드 external_user_id). 빈값=전체")
    args = parser.parse_args()
    if args.dry_run:
        os.environ["DELIVERY_DRY_RUN"] = "true"
    if args.mock:
        os.environ["ENABLE_MOCK_DATA"] = "true"
        from app.core.config import get_settings
        get_settings.cache_clear()   # 이미 캐시된 설정이 있으면 무효화
    if args.images:
        os.environ["FINBRIEF_IMAGE_STUB"] = "0"   # 실제 Gemini 이미지 생성

    result = run_batch(
        send_report=not args.no_report,
        send_cards=not args.no_cards,
        only_user=args.only_user or None,
    )
    print(
        f"[batch] status={result.status} "
        f"cards={len(result.generated_cards)} "
        f"deliveries={len(result.delivery_results)} "
        f"errors={len(result.errors)} report_url={(result.report or None) and result.report.report_url}"
    )
    for d in result.delivery_results:
        print(f"  deliver {d.topic_id}: {d.status}")


if __name__ == "__main__":
    main()
