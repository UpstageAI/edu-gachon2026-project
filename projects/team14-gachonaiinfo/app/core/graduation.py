"""졸업요건 정형 데이터 로딩/정규화.

학번별 파일(graduation_by_year.json)을 신뢰 원본으로 읽되, 그 파일이 없어 구
단일 파일(graduation_requirements.json)로 폴백하는 경우에도 **동일한 스키마**를
보장한다. 구 파일은 이수구분을 `이수구분별_최소학점{}`에 중첩했지만, 앱(졸업계산·
합성 문서)은 `전공필수/전공선택`을 최상위로 + 나머지 교양을 `교양{}`으로 기대한다.
polback 시 형태 불일치로 KeyError가 나지 않도록 여기서 정규화한다.

embeddings/DB를 import하지 않는 순수 로직(json만) → CI에서 키 없이 테스트된다.
"""

import json

# 전공(필수/선택)이 아닌 이수구분은 모두 '교양' 묶음으로 본다.
_MAJOR_KEYS = ("전공필수", "전공선택")


def normalize_graduation(rec: dict) -> dict:
    """졸업요건 레코드를 표준 형태(전공필수/전공선택 최상위 + 교양 dict)로 맞춘다.
    새 형태는 그대로(전공_합·교양 기본값만 보정), 구 형태는 변환한다. 멱등."""
    if "전공필수" in rec and "전공선택" in rec:
        out = dict(rec)
        out.setdefault("전공_합", (out.get("전공필수") or 0) + (out.get("전공선택") or 0))
        out.setdefault("교양", {})
        return out

    mins = rec.get("이수구분별_최소학점") or {}
    전필, 전선 = mins.get("전공필수"), mins.get("전공선택")
    교양 = {k: v for k, v in mins.items() if k not in _MAJOR_KEYS}
    out = {k: v for k, v in rec.items() if k != "이수구분별_최소학점"}
    out.update(
        {
            "전공필수": 전필,
            "전공선택": 전선,
            "전공_합": (전필 or 0) + (전선 or 0),
            "교양": 교양,
        }
    )
    out.setdefault("학부전공_원문", out.get("학과", "인공지능학과"))
    return out


def load_graduation_records(structured_dir) -> list[dict]:
    """학번별 졸업요건 리스트(정규화 완료). graduation_by_year.json 우선,
    없으면 구 단일 파일(graduation_requirements.json)로 폴백."""
    by_year = structured_dir / "graduation_by_year.json"
    if by_year.exists():
        records = json.loads(by_year.read_text(encoding="utf-8"))
    else:
        legacy = json.loads(
            (structured_dir / "graduation_requirements.json").read_text(encoding="utf-8")
        )
        records = [legacy]
    return [normalize_graduation(r) for r in records]
