"""학과 스코프 가드레일(detect_out_of_scope_department) 순수 로직 테스트.

이 챗봇은 인공지능학과(구 소프트웨어학과) 전용이다. 다른 학과명이 질문에 있으면
인공지능학과 자료로 답하지 않고 '전용 챗봇'임을 안내해야 한다.
"""

from app.graph.nodes import detect_out_of_scope_department


class TestOutOfScopeDepartment:
    def test_other_departments_detected(self):
        # 인공지능/소프트웨어 외 학과명이 있으면 그 학과명을 반환한다.
        assert detect_out_of_scope_department("23학번 컴퓨터공학과 졸업요건")
        assert detect_out_of_scope_department("컴퓨터공학과 졸업요건 알려줘")
        assert detect_out_of_scope_department("전자공학과 교육과정")
        assert detect_out_of_scope_department("간호학과 졸업요건 알려줘")
        assert detect_out_of_scope_department("경영학부 커리큘럼")
        # 인공지능학과가 같이 언급돼도 다른 학과가 있으면 스코프 밖으로 본다.
        assert detect_out_of_scope_department("인공지능학과 말고 컴퓨터공학과")

    def test_inscope_department_allowed(self):
        # 인공지능학과 / 소프트웨어학과(전신)는 스코프 안 → None.
        assert detect_out_of_scope_department("인공지능학과 교육목표 알려줘") is None
        assert detect_out_of_scope_department("소프트웨어학과랑 인공지능학과 차이") is None
        assert detect_out_of_scope_department("소프트웨어융합대학 소개") is None

    def test_generic_department_words_not_flagged(self):
        # 특정 학과명이 아닌 일반 지시어·학과사무실 등은 오탐하지 않는다.
        assert detect_out_of_scope_department("우리 학과 사무실 전화번호") is None
        assert detect_out_of_scope_department("학과사무실 전화번호 알려줘") is None
        assert detect_out_of_scope_department("타 학과로 전과하고 싶어") is None
        assert detect_out_of_scope_department("무슨 학과예요?") is None

    def test_non_department_questions_allowed(self):
        # 학과명이 아예 없는 일반 학사 질문은 통과한다.
        assert detect_out_of_scope_department("졸업하려면 몇 학점 필요해?") is None
        assert detect_out_of_scope_department("전공필수 뭐가 있어?") is None
        assert detect_out_of_scope_department("수강신청 언제야?") is None
