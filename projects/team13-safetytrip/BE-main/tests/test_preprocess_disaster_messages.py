"""
preprocessors/preprocess_disaster_messages.py의 순수 함수들에 대한 유닛테스트.
DB/API 연결 없이 실행 가능 (외부 의존성 없는 로직만 테스트).
"""
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from preprocessors.preprocess_disaster_messages import (
    split_region,
    parse_date,
    is_missing_person,
)


class TestSplitRegion:
    def test_basic_sido_sigungu(self):
        assert split_region("경기도 김포시 ") == ("경기도", "김포시")

    def test_sido_only_no_sigungu(self):
        # "경기도 전체" 처럼 시도 전체를 가리키는 경우도 sigungu 자리에 "전체"가 들어감
        assert split_region("경기도 전체") == ("경기도", "전체")

    def test_none_input(self):
        assert split_region(None) == (None, None)

    def test_empty_string(self):
        assert split_region("") == (None, None)

    def test_multi_word_sigungu(self):
        # 콤마로 구분된 여러 지역이 붙어있는 실제 데이터 케이스
        result = split_region("해운대구 우동,부산광역시 해운대구 중동")
        assert result[0] == "해운대구"


class TestParseDate:
    def test_valid_datetime(self):
        result = parse_date("2023/09/19 12:22:17", "%Y/%m/%d %H:%M:%S")
        assert result is not None
        assert result.year == 2023
        assert result.month == 9
        assert result.day == 19

    def test_valid_date_only(self):
        result = parse_date("2023-09-19", "%Y-%m-%d")
        assert result.year == 2023

    def test_none_input(self):
        assert parse_date(None, "%Y-%m-%d") is None

    def test_empty_string(self):
        assert parse_date("", "%Y-%m-%d") is None

    def test_wrong_format_returns_none(self):
        # 포맷이 안 맞으면 예외를 던지지 않고 None을 반환해야 함
        assert parse_date("not-a-date", "%Y-%m-%d") is None


class TestIsMissingPerson:
    def test_non_etc_disaster_type_always_false(self):
        # 기타가 아닌 카테고리는 절대 실종경보로 판별되지 않아야 함
        # (호우 등 실제 재난 상황 보고에서 '실종' 언급되는 경우 보호)
        msg = "실종된 주민을 찾습니다 ☎182"
        assert is_missing_person("호우", msg) is False

    def test_etc_with_182_phone(self):
        msg = "김포시에서 배회중인 김학균씨를 찾습니다 ☎182"
        assert is_missing_person("기타", msg) is True

    def test_etc_with_112_phone_and_keyword(self):
        # 182 대신 112로 안내되는 실종문자 케이스 (해운대구 사례에서 발견된 버그 수정분)
        msg = "연제구 주민인 정완모씨(남,82세)를 찾습니다 ☎112"
        assert is_missing_person("기타", msg) is True

    def test_etc_without_keywords_or_phone(self):
        # 진짜 기타 안전공지 (싱크홀 공사 등) - 실종경보 아님
        msg = "리가아파트 방면 도로 싱크홀 복구작업으로 통행에 주의 바랍니다"
        assert is_missing_person("기타", msg) is False

    def test_etc_with_dementia_keyword(self):
        msg = "치매를 앓고 있는 어르신이 실종되었습니다"
        assert is_missing_person("기타", msg) is True

    def test_none_message_content(self):
        assert is_missing_person("기타", None) is False