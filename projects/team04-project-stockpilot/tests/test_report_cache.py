from app.services import report_cache


async def test_report_cache_handles_cached_skipped_and_failed(monkeypatch):
    metadata_by_company = {
        "삼성전자": {
            "receipt_no": "202603170001",
            "corp_code": "00126380",
            "corp_name": "삼성전자",
            "stock_code": "005930",
            "report_name": "사업보고서",
            "received_date": "20260317",
            "source_url": "https://dart.example/samsung",
        },
        "NAVER": {
            "receipt_no": "202603180001",
            "corp_code": "00266961",
            "corp_name": "NAVER",
            "stock_code": "035420",
            "report_name": "사업보고서",
            "received_date": "20260318",
            "source_url": "https://dart.example/naver",
        },
        "카카오": {
            "receipt_no": "202603190001",
            "corp_code": "00258801",
            "corp_name": "카카오",
            "stock_code": "035720",
            "report_name": "사업보고서",
            "received_date": "20260319",
            "source_url": "https://dart.example/kakao",
        },
    }
    ingested = []

    async def fake_metadata(company):
        if company == "보고서없음":
            return None
        reverse_codes = {
            "005930": "삼성전자",
            "035420": "NAVER",
            "035720": "카카오",
        }
        company = reverse_codes.get(company, company)
        return metadata_by_company[company]

    async def fake_exists(source_id):
        return source_id == "dart:202603180001"

    async def fake_download(metadata):
        if metadata["corp_name"] == "카카오":
            raise RuntimeError("DART 일시 오류")
        return {**metadata, "content": "사업의 개요\n반도체 사업 설명"}

    async def fake_ingest(**kwargs):
        ingested.append(kwargs)
        return 12

    monkeypatch.setattr(
        report_cache.disclosure,
        "get_business_report_metadata",
        fake_metadata,
    )
    monkeypatch.setattr(report_cache.rag, "source_exists", fake_exists)
    monkeypatch.setattr(
        report_cache.disclosure,
        "download_business_report",
        fake_download,
    )
    monkeypatch.setattr(
        report_cache.rag,
        "ingest_business_report",
        fake_ingest,
    )

    summary = await report_cache.cache_business_reports(
        ["삼성전자", "NAVER", "보고서없음", "카카오"]
    )

    assert summary.total == 4
    assert summary.cached == 1
    assert summary.skipped == 2
    assert summary.failed == 1
    assert summary.items[0].chunks == 12
    assert summary.items[1].reason == "이미 캐시됨"
    assert summary.items[2].reason == "최근 사업보고서 없음"
    assert "DART 일시 오류" in summary.items[3].reason
    assert len(ingested) == 1
    assert ingested[0]["metadata"]["corp_code"] == "00126380"
