"""졸업요건 정규화(normalize_graduation) 테스트.

구 단일 파일(이수구분별_최소학점 중첩) → 새 형태(전공필수/전공선택 최상위 + 교양)
폴백 정규화가 KeyError 없이 일관 스키마를 보장하는지 고정한다.

app.core.graduation만 import(json만 의존) → CI에서 키 없이 실행된다.
"""

from app.core.graduation import normalize_graduation


def test_legacy_shape_is_converted():
    """구 형태(이수구분별_최소학점 중첩)를 최상위 전공필수/전공선택 + 교양으로 변환."""
    legacy = {
        "교육과정_연도": 2026,
        "학과": "인공지능학과",
        "총_졸업학점": 120,
        "이수구분별_최소학점": {
            "전공필수": 35,
            "전공선택": 37,
            "공통필수": 11,
            "공통선택": 13,
            "계열기초": None,
        },
        "비고": "구 형태",
    }
    out = normalize_graduation(legacy)
    assert out["전공필수"] == 35
    assert out["전공선택"] == 37
    assert out["전공_합"] == 72
    # 전공 외 이수구분은 교양 묶음으로.
    assert out["교양"] == {"공통필수": 11, "공통선택": 13, "계열기초": None}
    # 중첩 키는 제거된다.
    assert "이수구분별_최소학점" not in out
    assert out["총_졸업학점"] == 120


def test_new_shape_is_idempotent():
    """새 형태는 그대로 유지(전공_합/교양 기본값만 보정). 멱등."""
    new = {
        "교육과정_연도": 2022,
        "학과": "인공지능학과",
        "학부전공_원문": "AI·소프트웨어학부 소프트웨어전공",
        "총_졸업학점": 120,
        "전공필수": 38,
        "전공선택": 34,
        "전공_합": 72,
        "교양": {"기초교양": 17, "융합교양": 7},
        "비고": "새 형태",
    }
    out = normalize_graduation(new)
    assert out == new
    # 두 번 돌려도 동일(멱등).
    assert normalize_graduation(out) == new


def test_new_shape_without_optional_fields_gets_defaults():
    """전공_합/교양이 없어도 보정된다."""
    out = normalize_graduation({"교육과정_연도": 2025, "전공필수": 35, "전공선택": 37})
    assert out["전공_합"] == 72
    assert out["교양"] == {}
