"""
preprocessors/disaster_type_phone_map.py 유닛테스트.
"""
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from preprocessors.disaster_type_phone_map import get_contact, DISASTER_TYPE_PHONE_MAP


class TestGetContact:
    def test_known_disaster_type_returns_mapped_contact(self):
        result = get_contact("화재")
        assert result["phone"] == "119"

    def test_unknown_disaster_type_falls_back_to_default(self):
        result = get_contact("존재하지않는유형")
        assert result["phone"] == "110"
        assert result["agency"] == "정부민원 통합콜센터"

    def test_top_priority_disaster_types_have_contacts(self):
        # 재난문자 통계 상위권 유형들은 반드시 매핑되어 있어야 함
        must_have = ["폭염", "호우", "대설", "한파", "산불", "강풍", "산사태", "홍수", "태풍", "지진"]
        for disaster_type in must_have:
            assert disaster_type in DISASTER_TYPE_PHONE_MAP, (
                f"{disaster_type}이 DISASTER_TYPE_PHONE_MAP에서 빠져있음"
            )

    def test_all_contacts_have_phone_and_agency_keys(self):
        for disaster_type, contact in DISASTER_TYPE_PHONE_MAP.items():
            assert "phone" in contact, f"{disaster_type}에 phone 키 없음"
            assert "agency" in contact, f"{disaster_type}에 agency 키 없음"
            assert contact["phone"], f"{disaster_type}의 phone 값이 비어있음"