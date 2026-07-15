
from app.graph import compiled_graph


class TestGraph:
    async def test_price_path_end_to_end(self):
        result = await compiled_graph.ainvoke({"user_query": "상추 지금 비싸?"})
        assert result["route"] == "price"
        assert result["answer"]  # LLM이 생성한 자유 문장이라 내용 대신 비어있지 않은지만 확인
        judgments = result.get("judgment", [])
        assert len(judgments) > 0
        assert judgments[0]["status"] in ("비쌈", "적정", "쌈")

    async def test_price_path_contains_item_name(self):
        result = await compiled_graph.ainvoke({"user_query": "배추 요즘 비싸?"})
        assert result["route"] == "price"
        assert "배추" in result["answer"]

    async def test_offtopic_path(self):
        result = await compiled_graph.ainvoke({"user_query": "안녕하세요"})
        assert result["route"] == "off-topic"
        assert "answer" in result
        assert "에이전트" in result["answer"]

    async def test_price_data_populated(self):
        result = await compiled_graph.ainvoke({"user_query": "오이 시세 어때?"})
        assert result["route"] == "price"
        assert len(result.get("price_data", [])) > 0

    async def test_judgment_populated(self):
        result = await compiled_graph.ainvoke({"user_query": "상추 비싸?"})
        assert result["route"] == "price"
        judgments = result.get("judgment", [])
        assert len(judgments) > 0
        assert "status" in judgments[0]
        assert "diff_pct" in judgments[0]

    async def test_scenario1_rice_vs_instant_rice(self):
        # [시나리오 1] 쌀(KAMIS) + 즉석밥(참가격) 조합은 judge_price가 아니라
        # compare_items 경로를 타야 함. Router가 "즉석밥"/"햇반" 중 어떤 표현으로
        # 추출하든(둘 다 item_alias.py에 매핑돼 있음) 통과해야 하므로 정확한 문자열
        # 대신 alias 후보군으로 검증.
        result = await compiled_graph.ainvoke(
            {"user_query": "쌀 사서 밥 짓는 거랑 햇반 사 먹는 거 뭐가 싸?"}
        )
        assert result["route"] == "price"
        comparison = result.get("comparison")
        assert comparison is not None
        assert comparison["raw_item"] == "쌀"
        assert comparison["processed_item"] in ("즉석밥", "햇반")   
        assert comparison["raw_price_per_bowl"] > 0
        assert comparison["processed_price_per_bowl"] > 0
        assert comparison["cheaper_item"] in (comparison["raw_item"], comparison["processed_item"])
        assert comparison["raw_item"] in result["answer"]
        assert comparison["processed_item"] in result["answer"]
        # 이 조합은 judge_price를 건너뛰므로 judgment는 채워지지 않아야 함
        assert result.get("judgment", []) == []
