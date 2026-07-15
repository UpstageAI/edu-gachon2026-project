"""문의처 매칭(match_contact) 규칙 테스트.

'학과사무실 전화번호' 같은 연락처 질문이 contacts.json의 정확한 부서·번호로
매칭되는지 고정한다(무관한 RAG 문서에서 엉뚱한 번호를 긁어오던 회귀 방지).

app.repositories.contacts만 import하므로(app.config → contacts.json 파일만
읽음) 앱 그래프/embeddings 등 무거운 모듈을 끌어오지 않는다 → CI에서 API 키
없이도 실행된다.
"""

from app.repositories.contacts import contact_phone, format_contact, match_contact


def test_dept_office_phone_resolves():
    """학과사무실 연락처 질문은 인공지능학과 학과사무실 대표번호로 매칭된다."""
    for q in ("학과사무실 전화번호 알려줘", "인공지능학과 사무실 연락처"):
        c = match_contact(q)
        assert c["matched"] is True
        assert c["부서"] == "인공지능학과 학과사무실"
        assert contact_phone(c) == "031-750-8668"


def test_dept_office_phone_in_formatted_block():
    """LLM 그라운딩 블록에 실제 번호가 포함된다(지어내지 않도록 근거 제공)."""
    block = format_contact(match_contact("학과사무실 전화번호 알려줘"))
    assert "031-750-8668" in block
    assert "인공지능학과 학과사무실" in block


def test_topic_specific_departments():
    """주제별 문의처가 올바른 부서로 매칭되는지."""
    assert match_contact("국가장학금 어디에 문의해?")["부서"] == "학생복지처 장학복지팀"
    assert match_contact("기숙사 벌점 문의")["부서"] == "학생생활관(기숙사) 행정실"
    assert match_contact("도서관 대출 문의")["부서"] == "중앙도서관"


def test_unmatched_falls_back_without_fabricating():
    """매칭 실패 시 폴백 문구를 주되, 없는 번호를 지어내지 않는다."""
    c = match_contact("점심 뭐 먹을까")
    assert c["matched"] is False
    block = format_contact(c)
    # 폴백 문구엔 실제 대표 문의처 번호만 들어간다.
    assert "031-750-8668" in block or "031-750-5045" in block
