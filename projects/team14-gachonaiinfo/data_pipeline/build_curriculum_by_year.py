"""
Stage 2c: 학번(입학년도)별 전공교육과정 '요약' → 정형 JSON (다년도, RAG용)

과거(2021~2025) 전공교육과정표에서 학번별로 갈리는 핵심 사실만 요약해 담는다.
전체 과목·학점 정형화(build_catalog 수준)는 하지 않고, 학번별 차이가 큰
①트랙 구성 ②전공필수 핵심 과목 ③학과/전공 명칭을 정확히 담아 RAG 검색에 쓴다.
(개설과목 추천 도구 recommend_courses는 현행 2026만 사용 — 결정사항.)

원문(요람 교육과정표) 대조 확인:
  - 2021~2024는 'AI·소프트웨어학부'에 소프트웨어전공(트랙 Big Data/Smart Systems)과
    인공지능전공(트랙 Language-AI/Vision-AI, 2021엔 ABC 트랙도)이 공존했다. 2025~
    '인공지능학과'로 통합(트랙 Intelligent SW/AIoT/Vision & Language, 2026 +AI부트캠프).
    아래 요약의 트랙/전공필수는 소프트웨어전공 기준이며, 두 전공의 졸업 이수학점 요건은
    동일하다. ('인공지능학과=구 소프트웨어전공'은 사실이 아님.)
  - 전공필수 변화: 2021~2024는 로봇공학·경영학의 이해가 전공필수, 2025부터
    인공지능개론·컴퓨터네트워크가 전공필수로 편입.

전체 과목/학점의 정밀 값은 해당 년도 '요람'이 최종 근거 → 요약 문서는 그 점을 밝힌다.

출력:
  output/structured/curriculum_by_year.json  (2021~2025)
"""

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "output" / "structured" / "curriculum_by_year.json"

_SW = "AI·소프트웨어학부 소프트웨어전공"
_AI = "인공지능학과"

# 2021~2024 공통(Big Data / Smart Systems 체제) 트랙 구성
_BIGDATA = ["데이터과학", "머신러닝", "딥러닝", "빅데이터플랫폼"]
_SMART = ["사물인터넷개론", "드론과 로보틱스", "클라우드컴퓨팅시스템", "임베디드시스템"]
_TRACKS_SW = {"Big Data": _BIGDATA, "Smart Systems": _SMART}

# 2025 인공지능학과 트랙 구성
_TRACKS_AI25 = {
    "Intelligent SW": [
        "소프트웨어공학",
        "컴퓨터그래픽스",
        "고급웹프로그래밍",
        "HCI",
        "고급데이터베이스",
    ],
    "AIoT": ["AIoT 개론", "드론과 로보틱스", "클라우드컴퓨팅시스템", "사이버보안", "AIoT 시스템"],
    "Vision & Language": ["컴퓨터비전개론", "자연어처리개론", "AI수학", "AI프로젝트"],
}

# 전공필수 핵심 과목 (요람 공통과정 이수구분=전공필수)
_MAJOR_REQ_SW = [
    "프로그래밍기초",
    "소프트웨어수학",
    "기업과 리더십",
    "문제해결기법",
    "로봇공학",
    "자료구조 및 실습",
    "객체지향프로그래밍",
    "운영체제",
    "확률통계",
    "경영학의 이해",
    "P-실무프로젝트(졸업작품 I)",
    "졸업작품 II(캡스톤디자인)",
]
_MAJOR_REQ_AI25 = [
    "프로그래밍기초",
    "소프트웨어수학",
    "기업과 리더십",
    "문제해결기법",
    "자료구조 및 실습",
    "객체지향프로그래밍",
    "인공지능개론",
    "확률통계",
    "컴퓨터네트워크",
    "운영체제",
    "P-실무프로젝트(졸업작품 I)",
    "졸업작품 II(캡스톤디자인)",
]


def rec(year, 학부전공, 트랙, 전공필수, 비고):
    return {
        "교육과정_연도": year,
        "학과": _AI,
        "학부전공_원문": 학부전공,
        "트랙": 트랙,
        "전공필수_핵심": 전공필수,
        "비고": 비고,
    }


CURRICULUM_BY_YEAR = [
    rec(
        2021,
        _SW,
        _TRACKS_SW,
        _MAJOR_REQ_SW + ["웹프로그래밍"],
        "당시 AI·소프트웨어학부엔 소프트웨어전공(Big Data/Smart Systems 트랙)과 "
        "인공지능전공(Language-AI/Vision-AI 트랙)이 있었고, 두 전공의 졸업 이수학점 요건은 "
        "동일하다. 위 트랙 요약은 소프트웨어전공 기준. 전공선택은 각 트랙 과목에서 이수. "
        "전체 과목·학점은 2021 요람 참조.",
    ),
    rec(
        2022,
        _SW,
        _TRACKS_SW,
        _MAJOR_REQ_SW + ["웹프로그래밍"],
        "당시 AI·소프트웨어학부엔 소프트웨어전공(Big Data/Smart Systems 트랙)과 "
        "인공지능전공(Language-AI/Vision-AI 트랙)이 있었고, 두 전공의 졸업 이수학점 요건은 "
        "동일하다. 위 트랙 요약은 소프트웨어전공 기준. 전공선택은 각 트랙 과목에서 이수. "
        "전체 과목·학점은 2022 요람 참조.",
    ),
    rec(
        2023,
        _SW,
        _TRACKS_SW,
        _MAJOR_REQ_SW,
        "당시 AI·소프트웨어학부엔 소프트웨어전공(Big Data/Smart Systems 트랙)과 "
        "인공지능전공(Language-AI/Vision-AI 트랙)이 있었고, 두 전공의 졸업 이수학점 요건은 "
        "동일하다. 위 트랙 요약은 소프트웨어전공 기준. 전공선택은 각 트랙 과목에서 이수. "
        "전체 과목·학점은 2023 요람 참조.",
    ),
    rec(
        2024,
        _SW,
        _TRACKS_SW,
        _MAJOR_REQ_SW,
        "당시 AI·소프트웨어학부엔 소프트웨어전공(Big Data/Smart Systems 트랙)과 "
        "인공지능전공(Language-AI/Vision-AI 트랙)이 있었고, 두 전공의 졸업 이수학점 요건은 "
        "동일하다. 위 트랙 요약은 소프트웨어전공 기준. 전공선택은 각 트랙 과목에서 이수. "
        "전체 과목·학점은 2024 요람 참조.",
    ),
    rec(
        2025,
        _AI,
        _TRACKS_AI25,
        _MAJOR_REQ_AI25,
        "인공지능학과. 전공선택은 Intelligent SW/AIoT/Vision & Language 트랙에서 이수. "
        "전체 과목·학점은 2025 요람 참조.",
    ),
]


def validate():
    errs = []
    seen = set()
    for r in CURRICULUM_BY_YEAR:
        y = r["교육과정_연도"]
        if y in seen:
            errs.append(f"{y}: 연도 중복")
        seen.add(y)
        if not r["트랙"]:
            errs.append(f"{y}: 트랙 비어있음")
        if not r["전공필수_핵심"]:
            errs.append(f"{y}: 전공필수 비어있음")
    return errs


def main():
    errs = validate()
    print("=== 검증 ===")
    if errs:
        print("❌ 오류:")
        for e in errs:
            print("  -", e)
        raise SystemExit(1)
    print(f"✅ {len(CURRICULUM_BY_YEAR)}개 연도 통과")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(CURRICULUM_BY_YEAR, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[저장] {OUT.relative_to(ROOT)}")
    for r in CURRICULUM_BY_YEAR:
        print(
            f"  {r['교육과정_연도']}: 트랙 {list(r['트랙'])} / 전공필수 {len(r['전공필수_핵심'])}과목"
        )


if __name__ == "__main__":
    main()
