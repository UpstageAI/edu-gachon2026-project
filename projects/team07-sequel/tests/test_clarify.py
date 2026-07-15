"""값 레벨 ambiguity 되묻기 자기점검 — 분기·메시지가 깨지면 여기서 실패한다.

실행: .venv/bin/python -m tests.test_clarify  (또는 pytest)
"""
from app.graph.builder import _after_schema_link
from app.graph.nodes.formatter import format_answer

_AMB = {"keyword": "카드", "column": "olist_order_payments.payment_type",
        "value": "credit_card", "how": "ambiguous", "candidates": ["debit_card"]}


def test_clarify():
    # 그래프 분기: 애매(후보 실재) → format(되묻기), 그 외 → route
    assert _after_schema_link({"value_hints": [_AMB]}) == "format"
    assert _after_schema_link({"value_hints": [{**_AMB, "how": "exact", "candidates": []}]}) == "route"
    assert _after_schema_link({"value_hints": [{**_AMB, "candidates": []}]}) == "route"  # 후보 없으면 안 되묻음
    assert _after_schema_link({}) == "route"

    # formatter: LLM 없이 후보를 되묻는 고정 메시지 (top-1 + 후보 모두 노출)
    ans = format_answer({"question": "카드 결제 몇 건?", "value_hints": [_AMB]})["answer"]
    assert "credit_card" in ans["summary"] and "debit_card" in ans["summary"]
    assert "카드" in ans["summary"]
    assert ans["table"]["rows"] == [] and ans["sql"] == ""

    # 정상(비애매) 경로는 되묻기 분기를 안 탄다 — 무결과 안내로 진행
    ans2 = format_answer({"question": "q", "value_hints": [{**_AMB, "how": "exact"}],
                          "result": {"columns": [], "rows": []}})["answer"]
    assert "확인이 필요해요" not in ans2["summary"]


if __name__ == "__main__":
    test_clarify()
    print("ok")
