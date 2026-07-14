"""mask_pii 규칙 마스킹 자기점검 — 규칙이 깨지면 여기서 실패한다.

실행: .venv/bin/python -m tests.test_masking  (또는 pytest)
"""
from app.core.observability import mask_pii


def test_mask_pii():
    # PII 는 가린다
    assert mask_pii("문의: hong@acme.co.kr") == "문의: [EMAIL]"
    assert mask_pii("연락처 010-1234-5678") == "연락처 [PHONE]"
    assert mask_pii("01012345678 로 전화") == "[PHONE] 로 전화"
    assert mask_pii("주민 900101-1234567 확인") == "주민 [RRN] 확인"
    assert mask_pii("카드 4111 1111 1111 1111") == "카드 [CARD]"
    assert mask_pii("카드 4111111111111111") == "카드 [CARD]"
    # 일반 텍스트·짧은 숫자는 안 건드림(디버깅 가치 보존)
    assert mask_pii("주문 42건, 합계 3900원") == "주문 42건, 합계 3900원"
    # 비문자열은 그대로 통과(구조 훼손 방지)
    assert mask_pii(None) is None
    assert mask_pii(1234) == 1234
    assert mask_pii({"a": 1}) == {"a": 1}


if __name__ == "__main__":
    test_mask_pii()
    print("ok")
