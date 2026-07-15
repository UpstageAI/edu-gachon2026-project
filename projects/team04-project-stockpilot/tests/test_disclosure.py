import io
import zipfile

import httpx
import pytest

from app.repositories import disclosure as disclosure_repo
from app.repositories.disclosure import (
    DART_API_BASE,
    DartClient,
    extract_primary_document,
    parse_corporation_archive,
)


def test_parse_corporation_archive():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <result>
      <list>
        <corp_code>00126380</corp_code>
        <corp_name>삼성전자</corp_name>
        <stock_code>005930</stock_code>
      </list>
    </result>
    """
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("CORPCODE.xml", xml)

    corporations = parse_corporation_archive(archive_buffer.getvalue())

    assert corporations[0].corp_code == "00126380"
    assert corporations[0].stock_code == "005930"


def test_extract_primary_document_chooses_largest_text_file():
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("attachment.xml", "<p>짧은 첨부</p>")
        archive.writestr(
            "report.xml",
            "<html><body><h1>사업보고서</h1><p>"
            + ("충분히 긴 본문입니다. " * 20)
            + "</p></body></html>",
        )

    filename, content = extract_primary_document(archive_buffer.getvalue())

    assert filename == "report.xml"
    assert "사업보고서" in content


@pytest.mark.asyncio
async def test_list_disclosures_uses_business_report_filter():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["crtfc_key"] == "test-key"
        assert request.url.params["pblntf_detail_ty"] == "A001"
        return httpx.Response(
            200,
            json={
                "status": "000",
                "message": "정상",
                "list": [
                    {
                        "rcept_no": "20260317001234",
                        "corp_code": "00126380",
                        "corp_name": "삼성전자",
                        "stock_code": "005930",
                        "report_nm": "사업보고서 (2025.12)",
                        "rcept_dt": "20260317",
                    }
                ],
            },
        )

    async with httpx.AsyncClient(
        base_url=DART_API_BASE,
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = DartClient("test-key", client=http_client)
        rows = await client.list_disclosures(
            "00126380",
            begin_date="20260101",
            end_date="20261231",
            report_type="A001",
            limit=1,
        )

    assert rows[0]["rcept_no"] == "20260317001234"


@pytest.mark.asyncio
async def test_resolve_known_corporation_without_corp_code_download(monkeypatch):
    async def fail_get_corporations(self):
        raise AssertionError("known corporation should not download corpCode.xml")

    monkeypatch.setattr(DartClient, "get_corporations", fail_get_corporations)

    client = DartClient("test-key")
    by_stock_code = await client.resolve_corporation("005930")
    by_name = await client.resolve_corporation("삼성전자")
    sk_by_stock_code = await client.resolve_corporation("000660")
    sk_by_name = await client.resolve_corporation("SK하이닉스")
    sk_by_alias = await client.resolve_corporation("하이닉스")
    hanwha_by_stock_code = await client.resolve_corporation("042660")
    hanwha_by_name = await client.resolve_corporation("한화오션")
    hanwha_by_alias = await client.resolve_corporation("대우조선해양")
    celltrion_by_stock_code = await client.resolve_corporation("068270")
    celltrion_by_name = await client.resolve_corporation("셀트리온")
    rotem_by_stock_code = await client.resolve_corporation("064350")
    rotem_by_name = await client.resolve_corporation("현대로템")
    ecopro_by_stock_code = await client.resolve_corporation("247540")
    ecopro_by_name = await client.resolve_corporation("에코프로비엠")

    assert by_stock_code.corp_code == "00126380"
    assert by_name.stock_code == "005930"
    assert sk_by_stock_code.corp_code == "00164779"
    assert sk_by_name.stock_code == "000660"
    assert sk_by_alias.corp_code == "00164779"
    assert hanwha_by_stock_code.corp_code == "00111704"
    assert hanwha_by_name.stock_code == "042660"
    assert hanwha_by_alias.corp_code == "00111704"
    assert celltrion_by_stock_code.corp_code == "00413046"
    assert celltrion_by_name.stock_code == "068270"
    assert rotem_by_stock_code.corp_code == "00302926"
    assert rotem_by_name.stock_code == "064350"
    assert ecopro_by_stock_code.corp_code == "01160363"
    assert ecopro_by_name.stock_code == "247540"


@pytest.mark.asyncio
async def test_resolve_corporation_prefers_listed_duplicate_name():
    client = DartClient("test-key")
    client._corporations = [
        disclosure_repo.Corporation("00000001", "테스트", None),
        disclosure_repo.Corporation("00000002", "테스트", "123456"),
    ]

    resolved = await client.resolve_corporation("테스트")

    assert resolved.corp_code == "00000002"
    assert resolved.stock_code == "123456"


@pytest.mark.asyncio
async def test_get_recent_disclosures_reuses_short_cache(monkeypatch):
    monkeypatch.setattr(disclosure_repo.settings, "dart_api_key", "test-key")
    with disclosure_repo._DISCLOSURE_CACHE_LOCK:
        disclosure_repo._DISCLOSURE_CACHE.clear()

    calls = 0

    async def fake_resolve_corporation(self, corp):
        return disclosure_repo.Corporation("00126380", "Samsung Electronics", "005930")

    async def fake_list_disclosures(self, corp_code, *, limit):
        nonlocal calls
        calls += 1
        return [
            {
                "rcept_no": "20260317001234",
                "corp_code": corp_code,
                "corp_name": "Samsung Electronics",
                "stock_code": "005930",
                "report_nm": f"Business report {calls}",
                "rcept_dt": "20260317",
            }
        ][:limit]

    monkeypatch.setattr(
        disclosure_repo.DartClient,
        "resolve_corporation",
        fake_resolve_corporation,
    )
    monkeypatch.setattr(
        disclosure_repo.DartClient,
        "list_disclosures",
        fake_list_disclosures,
    )

    first = await disclosure_repo.get_recent_disclosures("005930", limit=3)
    second = await disclosure_repo.get_recent_disclosures("005930", limit=3)

    assert calls == 1
    assert second == first

    second[0]["report_name"] = "mutated"
    third = await disclosure_repo.get_recent_disclosures("005930", limit=3)
    assert third[0]["report_name"] == first[0]["report_name"]

    with disclosure_repo._DISCLOSURE_CACHE_LOCK:
        disclosure_repo._DISCLOSURE_CACHE.clear()
