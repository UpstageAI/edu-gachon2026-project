"""
preprocessors/parse_manual_guidelines.py의 파싱 로직 유닛테스트.
파일 I/O는 tmp_path fixture로 격리해서 테스트.
"""
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from preprocessors.parse_manual_guidelines import parse_file, DISASTER_TYPE_TO_DOMAIN


def write_temp_txt(tmp_path, content: str):
    p = tmp_path / "input.txt"
    p.write_text(content, encoding="utf-8")
    return str(p)


class TestParseFile:
    def test_single_valid_line(self, tmp_path):
        content = "[폭염 / 평상시 / 일반] 폭염은 열사병을 유발할 수 있습니다."
        path = write_temp_txt(tmp_path, content)

        result = parse_file(path)

        assert len(result) == 1
        assert result[0]["actRmks"] == "폭염은 열사병을 유발할 수 있습니다."
        assert result[0]["safety_cate_nm1"] == "자연재난"
        assert result[0]["safety_cate_nm2"] == "폭염"
        assert result[0]["safety_cate_nm3"] == "평상시 - 일반"

    def test_multiple_lines_and_blank_lines_skipped(self, tmp_path):
        content = (
            "[폭염 / 평상시 / 일반] 문장1\n"
            "\n"
            "[호우 / 발생시 / 대피] 문장2\n"
        )
        path = write_temp_txt(tmp_path, content)

        result = parse_file(path)

        assert len(result) == 2
        assert result[0]["safety_cate_nm2"] == "폭염"
        assert result[1]["safety_cate_nm2"] == "호우"

    def test_malformed_line_is_skipped_not_crashed(self, tmp_path):
        content = (
            "[폭염 / 평상시 / 일반] 정상 문장\n"
            "이 줄은 패턴에 안 맞음\n"
        )
        path = write_temp_txt(tmp_path, content)

        result = parse_file(path)

        # 패턴 안 맞는 줄은 스킵되고, 정상 줄만 결과에 포함
        assert len(result) == 1

    def test_domain_mapping_for_social_disaster(self, tmp_path):
        content = "[산불 / 대피시 / 일반] 산불 발생 시 대피합니다."
        path = write_temp_txt(tmp_path, content)

        result = parse_file(path)

        assert result[0]["safety_cate_nm1"] == "사회재난"

    def test_domain_mapping_for_life_safety(self, tmp_path):
        content = "[여름철물놀이 / 발생시 / 일반] 구명조끼를 착용합니다."
        path = write_temp_txt(tmp_path, content)

        result = parse_file(path)

        assert result[0]["safety_cate_nm1"] == "생활안전"

    def test_unknown_disaster_type_falls_back_to_natural(self, tmp_path):
        # DISASTER_TYPE_TO_DOMAIN에 없는 유형은 경고 후 '자연재난'으로 폴백
        content = "[알수없는유형 / 발생시 / 일반] 테스트 문장"
        path = write_temp_txt(tmp_path, content)

        result = parse_file(path)

        assert result[0]["safety_cate_nm1"] == "자연재난"

    def test_optional_fields_are_none(self, tmp_path):
        content = "[폭염 / 평상시 / 일반] 문장"
        path = write_temp_txt(tmp_path, content)

        result = parse_file(path)

        assert result[0]["contentsUrl"] is None
        assert result[0]["safety_cate1"] is None


class TestDomainMappingCompleteness:
    def test_all_top_priority_types_are_mapped(self):
        # 재난문자 통계 상위권 유형들이 매핑 딕셔너리에서 빠지지 않았는지 확인
        must_have = ["폭염", "호우", "산불", "대설", "한파", "강풍", "산사태", "홍수", "태풍", "지진"]
        for disaster_type in must_have:
            assert disaster_type in DISASTER_TYPE_TO_DOMAIN, (
                f"{disaster_type}이 DISASTER_TYPE_TO_DOMAIN에서 빠져있음"
            )