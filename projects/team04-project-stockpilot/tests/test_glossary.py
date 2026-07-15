import json
from types import SimpleNamespace

import httpx

from app.repositories import glossary


def test_rank_glossary_terms_prioritizes_exact_term_and_alias():
    rows = [
        {
            "term": "PBR",
            "definition": "Price Book-value Ratio",
            "category": "valuation",
            "aliases": ["Price Book-value Ratio"],
        },
        {
            "term": "PER",
            "definition": "Price Earnings Ratio",
            "category": "valuation",
            "aliases": ["Price Earnings Ratio"],
        },
    ]

    matches = glossary.rank_glossary_terms(rows, "PER이 뭐야?", limit=2)

    assert matches[0]["term"] == "PER"
    assert matches[0]["match_score"] >= 90


def test_extract_term_from_definition_question():
    assert glossary.extract_term_from_query("상장이 뭐야") == "상장"
    assert glossary.extract_term_from_query("PER이 뭐야?") == "PER"
    assert glossary.extract_term_from_query("보호예수 설명해") == "보호예수"
    assert glossary.extract_term_from_query("목표주가 뜻이 뭐야?") == "목표주가"
    assert glossary.extract_term_from_query("적정주가 뜻") == "적정주가"
    assert glossary.extract_term_from_query("공시가 뭔데?") == "공시"
    assert glossary.extract_term_from_query("공시라는 단어가 뭔 의미냐고") == "공시"
    assert glossary.extract_term_from_query("배고프다") is None


def test_find_terms_in_text_does_not_match_cb_inside_pcb():
    rows = [
        {
            "term": "전환사채",
            "definition": "주식으로 전환할 수 있는 채권입니다.",
            "aliases": ["CB", "Convertible Bond"],
        }
    ]

    assert glossary.find_terms_in_text("PCB 기판 수요가 늘었습니다.", rows) == []

    matches = glossary.find_terms_in_text("전환사채(CB)는 주식 전환 조건을 확인해야 합니다.", rows)
    assert [match["term"] for match in matches] == ["전환사채"]


def test_find_terms_in_text_matches_buy_term():
    rows = [
        {
            "term": "매수",
            "definition": "주식이나 채권 같은 금융상품을 사는 행위입니다.",
            "aliases": ["Buy", "매입"],
        }
    ]

    matches = glossary.find_terms_in_text("매수는 금융상품을 사는 행위입니다.", rows)

    assert matches[0]["term"] == "매수"
    assert matches[0]["matched_text"] == "매수"


async def test_research_external_term_uses_naver_encyclopedia(monkeypatch):
    monkeypatch.setattr(glossary.settings, "naver_client_id", "client-id")
    monkeypatch.setattr(glossary.settings, "naver_client_secret", "client-secret")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["query"] == "상장 주식 투자"
        assert request.headers["X-Naver-Client-Id"] == "client-id"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "title": "<b>상장</b>",
                        "description": "주식이 증권시장에 등록되어 일반 투자자가 거래할 수 있는 상태입니다.",
                        "link": "https://example.com/listing",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        entry = await glossary.research_external_term("상장이 뭐야", client=client)

    assert entry is not None
    assert entry["term"] == "상장"
    assert "증권시장" in entry["definition"]
    assert entry["metadata"]["provider"] == "naver_encyclopedia"


async def test_ingest_glossary_terms_upserts_structured_rows(tmp_path, monkeypatch):
    path = tmp_path / "glossary.json"
    path.write_text(
        json.dumps(
            [
                {
                    "term": "PER",
                    "definition": "Price Earnings Ratio",
                    "aliases": ["Price Earnings Ratio"],
                    "example": "PER 10 means price is 10x EPS.",
                    "source_url": "https://example.com/per",
                }
            ]
        ),
        encoding="utf-8",
    )
    captured = {}

    class FakeQuery:
        def upsert(self, rows, *, on_conflict):
            captured["rows"] = rows
            captured["on_conflict"] = on_conflict
            return self

        async def execute(self):
            return SimpleNamespace(data=captured["rows"])

    class FakeClient:
        def table(self, table_name):
            captured["table"] = table_name
            return FakeQuery()

    async def fake_client():
        return FakeClient()

    monkeypatch.setattr(glossary, "get_supabase_client", fake_client)

    saved = await glossary.ingest_glossary_terms(path)

    assert saved == 1
    assert captured["table"] == "glossary_terms"
    assert captured["on_conflict"] == "term"
    assert captured["rows"][0]["term"] == "PER"
    assert captured["rows"][0]["aliases"] == ["Price Earnings Ratio"]
    assert captured["rows"][0]["category"] == "valuation"


async def test_search_terms_reads_supabase_and_ranks_locally(monkeypatch):
    rows = [
        {
            "id": 1,
            "term": "PBR",
            "definition": "Price Book-value Ratio",
            "category": "valuation",
            "aliases": ["Price Book-value Ratio"],
            "difficulty": "beginner",
            "metadata": {},
        },
        {
            "id": 2,
            "term": "PER",
            "definition": "Price Earnings Ratio",
            "category": "valuation",
            "aliases": ["Price Earnings Ratio"],
            "difficulty": "beginner",
            "metadata": {},
        },
    ]

    class FakeQuery:
        def select(self, columns):
            self.columns = columns
            return self

        def limit(self, limit):
            self.limit_value = limit
            return self

        async def execute(self):
            return SimpleNamespace(data=rows)

    class FakeClient:
        def table(self, table_name):
            assert table_name == "glossary_terms"
            return FakeQuery()

    async def fake_client():
        return FakeClient()

    monkeypatch.setattr(glossary, "get_supabase_client", fake_client)

    matches = await glossary.search_terms("Price Earnings Ratio", limit=1)

    assert [match["term"] for match in matches] == ["PER"]


async def test_list_all_terms_includes_local_glossary_when_supabase_empty(monkeypatch):
    class FakeQuery:
        def select(self, columns):
            return self

        def limit(self, limit):
            return self

        async def execute(self):
            return SimpleNamespace(data=[])

    class FakeClient:
        def table(self, table_name):
            assert table_name == "glossary_terms"
            return FakeQuery()

    async def fake_client():
        return FakeClient()

    monkeypatch.setattr(glossary, "get_supabase_client", fake_client)

    terms = await glossary.list_all_terms()

    assert any(term["term"] == "매수" for term in terms)
