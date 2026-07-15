"""학번(입학년도) 인식 순수 로직 테스트.

app.core.admission만 import하므로(re 외 의존성 없음) 앱 그래프/embeddings 등
무거운 모듈을 끌어오지 않는다 → CI에서 API 키 없이도 실행된다.
"""

from app.core.admission import (
    applicable_curriculum_year,
    extract_admission_year,
    is_year_sensitive_question,
    parse_year_reply,
)


class TestExtractAdmissionYear:
    def test_two_digit(self):
        assert extract_admission_year("23학번 졸업요건 알려줘") == 2023
        assert extract_admission_year("저 21학번인데요") == 2021

    def test_four_digit(self):
        assert extract_admission_year("2022학번 교육과정") == 2022
        assert extract_admission_year("2019 학번") == 2019

    def test_requires_hakbeon_token(self):
        # '학번'이 없으면 학년/학점/년도 숫자는 학번이 아니다(오탐 방지).
        assert extract_admission_year("3학년 1학기 시간표") is None
        assert extract_admission_year("졸업까지 120학점 필요해?") is None
        assert extract_admission_year("2023년 일정 알려줘") is None

    def test_no_number(self):
        assert extract_admission_year("졸업요건 알려줘") is None
        assert extract_admission_year("") is None


class TestParseYearReply:
    def test_bare_number(self):
        assert parse_year_reply("23") == 2023
        assert parse_year_reply("2021") == 2021

    def test_with_hakbeon(self):
        assert parse_year_reply("23학번이요") == 2023
        assert parse_year_reply("21학번") == 2021

    def test_unparseable(self):
        assert parse_year_reply("몰라요") is None
        assert parse_year_reply("글쎄요") is None
        assert parse_year_reply("") is None


class TestIsYearSensitiveQuestion:
    def test_year_sensitive(self):
        assert is_year_sensitive_question("졸업요건 알려줘")
        assert is_year_sensitive_question("졸업 학점 얼마나 필요해?")
        assert is_year_sensitive_question("전공교육과정 이수구분 알려줘")
        assert is_year_sensitive_question("커리큘럼 어떻게 돼?")
        assert is_year_sensitive_question("전공 트랙 뭐가 있어?")

    def test_year_sensitive_graduation_combos(self):
        # "졸업" + 학점/이수/요건/몇 조합도 년도-민감(졸업 이수학점 기준).
        assert is_year_sensitive_question("졸업하려면 몇 학점 필요해?")
        assert is_year_sensitive_question("졸업하려면 학점 어떻게 돼?")
        assert is_year_sensitive_question("졸업 조건이 뭐야?")

    def test_not_year_sensitive(self):
        # 개설과목 추천·수강신청 일정·연락처는 현행이 맞으니 학번 무관.
        assert not is_year_sensitive_question("2학년 1학기 뭐 들어야 해?")
        assert not is_year_sensitive_question("수강신청 언제야?")
        assert not is_year_sensitive_question("학과사무실 전화번호")
        # 단독 '졸업 언제?'는 일정 질문 → 학번 무관.
        assert not is_year_sensitive_question("졸업식 언제야?")

    def test_current_track_name_not_year_sensitive(self):
        # 현행 트랙명을 콕 집으면 현행 기준이 분명 → 되묻지 않는다.
        assert not is_year_sensitive_question("AIoT 트랙은 무슨 과목이 있어?")
        assert not is_year_sensitive_question("Vision & Language 트랙 과목 알려줘")
        assert not is_year_sensitive_question("부트캠프 과정 뭐 있어?")
        # 트랙명 없는 일반 트랙 질문은 여전히 년도-민감(구성이 학번별로 다름).
        assert is_year_sensitive_question("전공 트랙 뭐가 있어?")

    def test_graduation_non_requirement_not_sensitive(self):
        # '졸업' + 학점/이수/요건 없이 bare 숫자질문은 요건이 아니므로 학번 무관.
        assert not is_year_sensitive_question("졸업작품 몇 학년에 해?")
        assert not is_year_sensitive_question("사회봉사 몇 시간 해야 졸업해?")
        # 반면 졸업요건성(학점/조건 동반)은 여전히 년도-민감.
        assert is_year_sensitive_question("졸업하려면 몇 학점 필요해?")


class TestApplicableCurriculumYear:
    def test_exact_match(self):
        assert applicable_curriculum_year(2023, {2021, 2022, 2023, 2026}) == 2023

    def test_newer_than_available_uses_latest(self):
        assert applicable_curriculum_year(2027, {2021, 2022, 2026}) == 2026

    def test_older_than_available_uses_earliest(self):
        assert applicable_curriculum_year(2019, {2021, 2022, 2026}) == 2021

    def test_gap_uses_nearest_not_greater(self):
        # 2024학번인데 2024 데이터가 없으면 개정 전 최신인 2022를 적용.
        assert applicable_curriculum_year(2024, {2021, 2022, 2026}) == 2022

    def test_no_data(self):
        assert applicable_curriculum_year(2023, set()) is None
        assert applicable_curriculum_year(2023, {None}) is None

    def test_only_current_year_maps_everything_to_it(self):
        # Phase 1(2026 데이터만): 모든 학번이 2026으로 → 현행 동작 보존.
        for yr in (2021, 2022, 2023, 2024, 2025, 2026):
            assert applicable_curriculum_year(yr, {2026}) == 2026
