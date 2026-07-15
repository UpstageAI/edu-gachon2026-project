from app.schemas.documents import BusinessReportFacts, ParsedDocument
from app.services import document_ingestion


async def test_business_report_ingestion_saves_chunks_and_facts(
    monkeypatch,
    tmp_path,
):
    path = tmp_path / "report.pdf"
    path.write_bytes(b"mock-pdf")
    calls = {}

    async def fake_parse_document(*args, **kwargs):
        return ParsedDocument(
            content="# 사업의 개요\n반도체 사업 설명",
            parser="upstage-document-parse",
            output_format="markdown",
            page_count=2,
        )

    async def fake_extract(*args, **kwargs):
        return BusinessReportFacts(
            company_name="삼성전자",
            risk_factors=["메모리 가격 변동"],
        )

    async def fake_ingest(**kwargs):
        calls["ingest"] = kwargs
        return 8

    async def fake_save_facts(**kwargs):
        calls["facts"] = kwargs

    monkeypatch.setattr(document_ingestion, "parse_document", fake_parse_document)
    monkeypatch.setattr(
        document_ingestion,
        "extract_business_report_facts",
        fake_extract,
    )
    monkeypatch.setattr(
        document_ingestion,
        "ingest_business_report",
        fake_ingest,
    )
    monkeypatch.setattr(
        document_ingestion,
        "save_document_facts",
        fake_save_facts,
    )

    result = await document_ingestion.ingest_document(
        path,
        source_id="report:1",
        metadata={"source_type": "business_report"},
        document_type="business_report",
        extract_facts=True,
    )

    assert result.chunks_saved == 8
    assert result.parser == "upstage-document-parse"
    assert result.facts_saved is True
    assert calls["ingest"]["metadata"]["page_count"] == 2
    assert calls["facts"]["facts"].risk_factors == ["메모리 가격 변동"]
