import logging

import pytest
from langchain_core.messages import HumanMessage

from app.graph.nodes import mask_personal_info_node
from app.graph.state import create_initial_state
from app.privacy.masking import mask_personal_info_with_details


@pytest.mark.parametrize(
    ("personal_info", "mask"),
    [
        ("hong@example.com", "[이메일]"),
        ("900101-1234567", "[주민등록번호]"),
        ("010-1234-5678", "[전화번호]"),
        ("02-123-4567", "[전화번호]"),
        ("1234-5678-9012-3456", "[카드번호]"),
        ("이름: 홍길동", "이름: [이름]"),
        ("주소: 서울시 중구 세종대로", "주소: [주소]"),
        ("계좌번호: 123-456-789012", "계좌번호: [계좌번호]"),
        ("여권번호: M12345678", "여권번호: [여권번호]"),
    ],
)
def test_mask_personal_info(personal_info, mask):
    masked = mask_personal_info_with_details(f"문의입니다. {personal_info}")["masked_text"]

    assert personal_info not in masked
    assert mask in masked


def test_mask_node_keeps_original_message():
    original = "제 번호는 010-1234-5678입니다."
    state = create_initial_state("session", messages=[HumanMessage(content=original)])

    update = mask_personal_info_node(state)

    assert state["messages"][0].content == original
    assert update["masked_text"] == "제 번호는 [전화번호]입니다."


def test_masking_log_contains_counts_but_not_personal_info(caplog):
    personal_info = "010-1234-5678 hong@example.com"

    with caplog.at_level(logging.INFO, logger="app.privacy.masking"):
        mask_personal_info_with_details(personal_info)

    assert "총=2건" in caplog.text
    assert "전화번호=1건" in caplog.text
    assert "이메일=1건" in caplog.text
    assert "010-1234-5678" not in caplog.text
    assert "hong@example.com" not in caplog.text
