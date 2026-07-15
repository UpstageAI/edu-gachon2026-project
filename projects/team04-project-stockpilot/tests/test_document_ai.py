from langchain_core.documents import Document

from app.repositories import document_ai
from app.schemas.documents import BusinessReportFacts


async def test_document_parse_uses_upstage_markdown(monkeypatch, tmp_path):
    path = tmp_path / "report.pdf"
    path.write_bytes(b"mock-pdf")
    monkeypatch.setattr(document_ai.settings, "upstage_api_key", "test-key")
    captured = {}

    class FakeLoader:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def load(self):
            return [
                Document(
                    page_content="# 사업의 개요\n반도체 사업",
                    metadata={"page": 0},
                ),
                Document(
                    page_content="# 위험요인\n시장 변동 위험",
                    metadata={"page": 1},
                ),
            ]

    parsed = await document_ai.parse_document(
        path,
        loader_factory=FakeLoader,
    )

    assert parsed.parser == "upstage-document-parse"
    assert parsed.output_format == "markdown"
    assert parsed.page_count == 2
    assert "# 사업의 개요" in parsed.content
    assert captured["output_format"] == "markdown"
    assert captured["split"] == "page"


async def test_document_parse_local_fallback_for_text(tmp_path):
    path = tmp_path / "report.md"
    path.write_text("# 사업의 개요\n반도체 사업", encoding="utf-8")

    parsed = await document_ai.parse_document(path)

    assert parsed.parser == "local-fallback"
    assert parsed.output_format == "text"
    assert parsed.page_count == 1


async def test_information_extract_uses_business_report_schema(
    monkeypatch,
    tmp_path,
):
    path = tmp_path / "report.pdf"
    path.write_bytes(b"mock-pdf")
    monkeypatch.setattr(document_ai.settings, "upstage_api_key", "test-key")
    captured = {}

    class FakeExtractor:
        async def ainvoke(self, payload):
            captured.update(payload)
            return {
                "company_name": "삼성전자",
                "report_period": "2025",
                "business_summary": "반도체와 모바일 사업",
                "major_products": ["메모리", "스마트폰"],
                "risk_factors": ["메모리 가격 변동"],
                "lawsuits": [],
                "regulatory_actions": [],
                "audit_opinion": "적정",
            }

    def extractor_factory(**kwargs):
        assert kwargs["api_key"] == "test-key"
        return FakeExtractor()

    facts = await document_ai.extract_business_report_facts(
        path,
        extractor_factory=extractor_factory,
    )

    assert isinstance(facts, BusinessReportFacts)
    assert facts.company_name == "삼성전자"
    assert facts.risk_factors == ["메모리 가격 변동"]
    response_format = captured["response_format"]
    assert response_format["json_schema"]["name"] == "business_report_facts"
    schema = response_format["json_schema"]["schema"]
    assert "risk_factors" in schema["properties"]
    assert all("type" in field for field in schema["properties"].values())
    assert set(schema["required"]) == set(schema["properties"])
