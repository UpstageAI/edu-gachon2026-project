"""
app/graph/nodes.py의 parse_node 이어받기(carry-forward) 로직 유닛테스트.
체크포인터가 복원해준 '이전 턴 state'를 실제로 활용하는지 검증.
DB/API 호출 없이 parse_user_query만 monkeypatch로 대체.
"""
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import app.graph.nodes as nodes_module


class TestParseNodeCarryForward:
    def test_no_previous_state_uses_only_current_parse(self, monkeypatch):
        """체크포인터 없이(첫 턴) 호출되면 이전 값이 없으니 그냥 현재 파싱 결과만 씀"""
        monkeypatch.setattr(nodes_module, "parse_user_query", lambda q: {
            "region_sido": "부산광역시", "region_sigungu": "해운대구",
            "month": 8, "intent": "prevention", "disaster_type": None,
            "has_vulnerable": True,
        })

        result = nodes_module.parse_node({"user_query": "8월에 해운대 여행"})

        assert result["region_sido"] == "부산광역시"
        assert result["month"] == 8
        assert result["has_vulnerable"] is True

    def test_followup_question_inherits_previous_region_and_month(self, monkeypatch):
        """후속 질문이 지역/시기를 안 언급해도 이전 턴 값을 이어받아야 함"""
        monkeypatch.setattr(nodes_module, "parse_user_query", lambda q: {
            "region_sido": None, "region_sigungu": None,
            "month": None, "intent": "prevention", "disaster_type": None,
            "has_vulnerable": False,
        })

        previous_state = {
            "user_query": "그럼 노약자는 뭘 더 챙겨야 해?",
            "region_sido": "부산광역시",
            "region_sigungu": "해운대구",
            "month": 8,
            "has_vulnerable": True,
        }

        result = nodes_module.parse_node(previous_state)

        assert result["region_sido"] == "부산광역시"
        assert result["region_sigungu"] == "해운대구"
        assert result["month"] == 8
        assert result["has_vulnerable"] is True  # 이전에 True였으면 계속 유지

    def test_new_message_overrides_previous_region(self, monkeypatch):
        """새 질문이 다른 지역을 명시하면 이전 값 대신 새 값을 써야 함"""
        monkeypatch.setattr(nodes_module, "parse_user_query", lambda q: {
            "region_sido": "강원도", "region_sigungu": "평창군",
            "month": None, "intent": "prevention", "disaster_type": None,
            "has_vulnerable": False,
        })

        previous_state = {
            "user_query": "이번엔 평창 갈 건데",
            "region_sido": "부산광역시",
            "region_sigungu": "해운대구",
            "month": 8,
            "has_vulnerable": False,
        }

        result = nodes_module.parse_node(previous_state)

        assert result["region_sido"] == "강원도"  # 새 값으로 갈아치워짐
        assert result["region_sigungu"] == "평창군"
        assert result["month"] == 8  # month는 새 질문에 없어서 이전 값 유지

    def test_intent_always_recomputed_not_carried_forward(self, monkeypatch):
        """intent는 매번 새로 판단해야 함 (이전 턴이 prevention이었어도 이번엔 다를 수 있음)"""
        monkeypatch.setattr(nodes_module, "parse_user_query", lambda q: {
            "region_sido": None, "region_sigungu": None,
            "month": None, "intent": "reactive", "disaster_type": "호우",
            "has_vulnerable": False,
        })

        previous_state = {
            "user_query": "호우경보 왔어",
            "region_sido": "부산광역시",
            "intent": "prevention",
        }

        result = nodes_module.parse_node(previous_state)

        assert result["intent"] == "reactive"  # 이전 turn의 intent를 그대로 이어받지 않음

    def test_disaster_type_carried_forward_when_not_mentioned(self, monkeypatch):
        monkeypatch.setattr(nodes_module, "parse_user_query", lambda q: {
            "region_sido": None, "region_sigungu": None,
            "month": None, "intent": "reactive", "disaster_type": None,
            "has_vulnerable": False,
        })

        previous_state = {
            "user_query": "그거 말고 다른 방법은 없어?",
            "disaster_type": "호우",
        }

        result = nodes_module.parse_node(previous_state)

        assert result["disaster_type"] == "호우"