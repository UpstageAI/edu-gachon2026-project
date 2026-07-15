"""주요 종목의 최신 사업보고서를 Supabase RAG에 미리 적재합니다."""

from __future__ import annotations

from collections.abc import Iterable

from loguru import logger

from app.repositories import disclosure, rag
from app.schemas.cache import BusinessReportCacheItem, BusinessReportCacheSummary

POPULAR_COMPANIES = {
    "삼성전자": "005930",
    "SK하이닉스": "000660",
    "LG에너지솔루션": "373220",
    "삼성바이오로직스": "207940",
    "현대차": "005380",
    "기아": "000270",
    "NAVER": "035420",
    "카카오": "035720",
    "POSCO홀딩스": "005490",
    "셀트리온": "068270",
}


async def cache_business_reports(
    companies: Iterable[str] | None = None,
    *,
    refresh: bool = False,
) -> BusinessReportCacheSummary:
    """최신 사업보고서를 순차 적재하고 기업별 결과를 반환합니다."""
    company_list = list(dict.fromkeys(companies or POPULAR_COMPANIES))
    targets = [
        (company, POPULAR_COMPANIES.get(company, company)) for company in company_list
    ]
    items: list[BusinessReportCacheItem] = []

    for index, (company, query) in enumerate(targets, start=1):
        logger.info(f"사업보고서 캐시 {index}/{len(targets)}: {company}")
        try:
            metadata = await disclosure.get_business_report_metadata(query)
            if metadata is None:
                items.append(
                    BusinessReportCacheItem(
                        company=company,
                        status="skipped",
                        reason="최근 사업보고서 없음",
                    )
                )
                continue

            source_id = f"dart:{metadata['receipt_no']}"
            if not refresh and await rag.source_exists(source_id):
                items.append(
                    BusinessReportCacheItem(
                        company=company,
                        status="skipped",
                        source_id=source_id,
                        reason="이미 캐시됨",
                    )
                )
                continue

            report = await disclosure.download_business_report(metadata)
            chunks = await rag.ingest_business_report(
                source_id=source_id,
                content=report["content"],
                metadata={
                    "source_type": "dart",
                    "status": "active",
                    "title": report["report_name"],
                    "corp_code": report["corp_code"],
                    "corp_name": report["corp_name"],
                    "stock_code": report["stock_code"],
                    "received_date": report["received_date"],
                    "source_url": report["source_url"],
                    "receipt_no": report["receipt_no"],
                },
            )
            items.append(
                BusinessReportCacheItem(
                    company=company,
                    status="cached",
                    source_id=source_id,
                    chunks=chunks,
                )
            )
        except Exception as exc:
            logger.exception(f"사업보고서 캐시 실패: {company}")
            items.append(
                BusinessReportCacheItem(
                    company=company,
                    status="failed",
                    reason=f"{type(exc).__name__}: {exc}",
                )
            )

    return BusinessReportCacheSummary(
        total=len(items),
        cached=sum(item.status == "cached" for item in items),
        skipped=sum(item.status == "skipped" for item in items),
        failed=sum(item.status == "failed" for item in items),
        items=items,
    )
