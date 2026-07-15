"""
Stage 2: 교육과정표 → 정형 JSON 카탈로그

Stage 1(parse_pdf.py) 출력의 표를 사람이 소계(小計)와 대조 검증하여 정형화한 결과를
코드로 담고, 재검증한 뒤 JSON으로 내보낸다. (학수번호는 원문에 없으므로 제외)

정형화 근거:
  - 원문은 좌(1학기)/우(2학기) 2단 인터리빙 표. 좌우를 각각 과목 레코드로 분리.
  - OCR 중복행 제거: '고급웹프로그래밍' 중복, 4-2 우측 '학생자율연구/테크기업경영' 병합 복원.
  - 익명 '공통선택' placeholder 행은 명명 과목이 아니므로 카탈로그에서 제외
    (졸업요건의 공통선택 13학점으로만 반영).
  - 각 그룹 소계와 대조하여 검증(맨 아래 validate()).

출력:
  output/structured/course_catalog.json
  output/structured/graduation_requirements.json
"""

import json
import pathlib
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "output" / "structured"

YEAR = 2026

# 이수구분: 공통필수 / 공통선택 / 전공필수 / 전공선택
# 트랙: 공통 / Intelligent SW / AIoT / Vision & Language / AI부트캠프
# 필드: (교과목명, 이수구분, 학점, 이론, 실습, 학년, 학기, 트랙)
# 학기: 1 | 2 | "매학기" | "계절학기"


def c(name, gubun, credit, theory, practice, year, term, track="공통"):
    return {
        "교과목명": name,
        "이수구분": gubun,
        "학점": credit,
        "이론": theory,
        "실습": practice,
        "개설학년": year,
        "개설학기": term,
        "트랙": track,
        "교육과정_연도": YEAR,
    }


# ────────────────────────────────────────────────────────────
# 공통과정 (인공지능학과 공통) — 명명 과목만. '공통선택' placeholder 제외.
# ────────────────────────────────────────────────────────────
COMMON = [
    # 1학년 1학기
    c("College English 1", "공통필수", 1, 0, 2, 1, 1),
    c("가천인세미나", "공통필수", 1, 0, 1, 1, 1),
    c("AI-Ntree", "공통필수", 1, 0, 2, 1, 1),  # OCR 'Al-Ntree' 보정
    c("AI 중심세상", "공통필수", 2, 2, 0, 1, 1),
    c("프로그래밍기초", "전공필수", 3, 2, 1, 1, 1),
    c("소프트웨어수학", "전공필수", 3, 3, 0, 1, 1),
    # 1학년 2학기
    c("College English 2", "공통필수", 1, 0, 2, 1, 2),
    c("AI 프로그래밍입문", "공통필수", 2, 1, 1, 1, 2),
    c("AI와 글쓰기", "공통필수", 2, 2, 0, 1, 2),
    c("기업과 리더십", "전공필수", 2, 2, 0, 1, 2),
    c("문제해결기법", "전공필수", 3, 2, 1, 1, 2),
    c("오픈소스SW", "전공선택", 2, 1, 1, 1, 2),
    # 2학년 1학기
    c("자료구조 및 실습", "전공필수", 3, 2, 1, 2, 1),
    c("객체지향프로그래밍", "전공필수", 3, 2, 1, 2, 1),
    c("인공지능개론", "전공필수", 3, 2, 1, 2, 1),
    c("확률통계", "전공필수", 3, 3, 0, 2, 1),
    # 2학년 2학기
    c("컴퓨터네트워크", "전공필수", 3, 2, 1, 2, 2),
    c("알고리즘", "전공선택", 3, 2, 1, 2, 2),
    c("데이터베이스", "전공선택", 3, 3, 0, 2, 2),
    c("경영학 이해", "전공선택", 3, 3, 0, 2, 2),
    # 3학년 1학기
    c("운영체제", "전공필수", 3, 3, 0, 3, 1),
    c("모바일프로그래밍", "전공선택", 3, 2, 1, 3, 1),
    c("디지털마케팅", "전공선택", 3, 3, 0, 3, 1),
    c("AI 네트워크보안", "전공선택", 3, 3, 0, 3, 1),
    c("데이터과학", "전공선택", 3, 2, 1, 3, 1),
    # 3학년 2학기
    c("취·창업 진로세미나", "공통필수", 1, 1, 0, 3, 2),
    c("P-실무프로젝트 (졸업작품I)", "전공필수", 3, 7, 8, 3, 2),
    c("컴퓨터구조", "전공선택", 3, 4, 0, 3, 2),
    c("머신러닝", "전공선택", 3, 2, 2, 3, 2),
    # 4학년 1학기
    c("졸업작품 II (캡스톤디자인)", "전공필수", 3, 0, 3, 4, 1),
    c("딥러닝", "전공선택", 3, 2, 1, 4, 1),
    c("현장실습", "전공선택", 1, 0, 2, 4, 1),
    c("AI·SW신기술특론", "전공선택", 3, 2, 1, 4, 1),
    # 4학년 2학기 (OCR '학생자울연구 테크기업경영' 병합행 복원)
    c("학생자율연구", "전공선택", 3, 1, 2, 4, 2),
    c("테크기업경영", "전공선택", 3, 3, 0, 4, 2),
]

# ────────────────────────────────────────────────────────────
# 트랙과정 (전공선택). OCR 중복행 제거 완료.
# ────────────────────────────────────────────────────────────
TRACK = [
    # Intelligent SW 트랙
    c("소프트웨어공학", "전공선택", 3, 2, 1, 3, 1, "Intelligent SW"),
    c("컴퓨터그래픽스", "전공선택", 3, 2, 2, 3, 2, "Intelligent SW"),
    c("고급웹프로그래밍", "전공선택", 3, 2, 1, 4, 1, "Intelligent SW"),
    c("HCI", "전공선택", 3, 2, 1, 4, 2, "Intelligent SW"),
    c("고급데이터베이스", "전공선택", 3, 2, 1, 4, 2, "Intelligent SW"),
    # AIoT 트랙
    c("AIoT 개론", "전공선택", 3, 3, 0, 3, 1, "AIoT"),
    c("드론과 로보틱스", "전공선택", 3, 2, 2, 3, 2, "AIoT"),
    c("클라우드컴퓨팅시스템", "전공선택", 3, 2, 1, 4, 1, "AIoT"),
    c("사이버보안", "전공선택", 3, 2, 1, 4, 1, "AIoT"),
    c("AIoT 시스템", "전공선택", 3, 2, 1, 4, 2, "AIoT"),
    # Vision & Language 트랙
    c("컴퓨터비전개론", "전공선택", 3, 2, 1, 3, 1, "Vision & Language"),
    c("자연어처리개론", "전공선택", 3, 2, 2, 3, 2, "Vision & Language"),
    c("AI수학", "전공선택", 3, 3, 0, 4, 1, "Vision & Language"),
    c("AI프로젝트", "전공선택", 3, 1, 2, 4, 2, "Vision & Language"),
]

# ────────────────────────────────────────────────────────────
# AI부트캠프 교육과정 (전공선택)
# ────────────────────────────────────────────────────────────
BOOTCAMP = [
    c("인공지능 입문", "전공선택", 3, 3, 0, 0, "매학기", "AI부트캠프"),  # 학년='전체'→0
    c("머신러닝 및 실습", "전공선택", 3, 6, 3, 4, "매학기", "AI부트캠프"),
    c("생성형 AI 활용", "전공선택", 3, 6, 3, 4, "매학기", "AI부트캠프"),
    c("온디바이스 AI", "전공선택", 3, 6, 3, 4, "매학기", "AI부트캠프"),
    c("생성형 AI 심화", "전공선택", 3, 6, 3, 4, "매학기", "AI부트캠프"),
    c("로보틱스 AI", "전공선택", 3, 6, 3, 4, "매학기", "AI부트캠프"),
    c("생성형 AI 고급", "전공선택", 3, 1, 2, 4, "계절학기", "AI부트캠프"),
    c("현장 미러형 프로젝트", "전공선택", 3, 1, 2, 4, "계절학기", "AI부트캠프"),
    c("생성형 AI 에이전트", "전공선택", 3, 1, 2, 4, "계절학기", "AI부트캠프"),
]

CATALOG = COMMON + TRACK + BOOTCAMP

# ────────────────────────────────────────────────────────────
# 졸업 이수학점 (원본 ibook 대조 확인 완료 — 사용자 확정)
# ────────────────────────────────────────────────────────────
GRADUATION = {
    "교육과정_연도": YEAR,
    "학과": "인공지능학과",
    "총_졸업학점": 120,
    "이수구분별_최소학점": {
        "전공필수": 35,
        "전공선택": 37,
        "공통필수": 11,
        "공통선택": 13,
        "계열기초": None,  # 원문 '-' (해당 없음)
    },
    "비고": "트랙 무관 공통 기준. 전공선택 37학점은 3개 트랙/부트캠프 과목에서 이수.",
}

# 검증용 기대 소계: (그룹키) -> 학점 합
EXPECTED_SUBTOTALS = {
    # 공통과정 (좌=1학기 / 우=2학기) 학점 소계
    ("공통", 1, 1): 15,
    ("공통", 1, 2): 17,
    ("공통", 2, 1): 14,
    ("공통", 2, 2): 14,
    ("공통", 3, 1): 15,
    ("공통", 3, 2): 10,
    ("공통", 4, 1): 10,
    ("공통", 4, 2): 6,
    # 단, 공통과정 소계에는 익명 '공통선택'(placeholder) 학점이 포함되어 있으므로
    # 아래 validate()는 명명 과목만 합산한 값과 '기대-placeholder'를 비교한다.
}
# 각 (학년,학기)별 익명 공통선택 placeholder 학점 (원문 소계 맞추기용)
COMMON_ELECTIVE_PLACEHOLDER = {
    (1, 1): 4,  # 2+2
    (1, 2): 5,  # 2+3
    (2, 1): 2,  # 2
    (2, 2): 2,  # 2
    (3, 1): 0,
    (3, 2): 0,
    (4, 1): 0,
    (4, 2): 0,
}
TRACK_SUBTOTALS = {
    "Intelligent SW": 15,
    "AIoT": 15,
    "Vision & Language": 12,
}
BOOTCAMP_TOTAL = 27


def validate():
    errs, warns = [], []

    # 1) 공통과정 (학년,학기) 학점 소계 = 명명과목합 + placeholder
    common_by = defaultdict(int)
    for co in COMMON:
        common_by[(co["개설학년"], co["개설학기"])] += co["학점"]
    for (y, t), expected in [((k[1], k[2]), v) for k, v in EXPECTED_SUBTOTALS.items()]:
        named = common_by[(y, t)]
        ph = COMMON_ELECTIVE_PLACEHOLDER[(y, t)]
        if named + ph != expected:
            errs.append(
                f"공통 {y}-{t}학기 소계 불일치: 명명 {named} + placeholder {ph} = {named + ph} ≠ 원문 {expected}"
            )

    # 2) 트랙 소계
    track_by = defaultdict(int)
    for co in TRACK:
        track_by[co["트랙"]] += co["학점"]
    for trk, expected in TRACK_SUBTOTALS.items():
        if track_by[trk] != expected:
            errs.append(f"{trk} 트랙 소계 불일치: {track_by[trk]} ≠ 원문 {expected}")

    # 3) 부트캠프 소계
    bc = sum(co["학점"] for co in BOOTCAMP)
    if bc != BOOTCAMP_TOTAL:
        errs.append(f"AI부트캠프 소계 불일치: {bc} ≠ 원문 {BOOTCAMP_TOTAL}")

    # 4) 중복 (교과목명, 트랙, 학년, 학기)
    seen = set()
    for co in CATALOG:
        key = (co["교과목명"], co["트랙"], co["개설학년"], co["개설학기"])
        if key in seen:
            errs.append(f"중복 과목: {key}")
        seen.add(key)

    # 5) 참고: 명명 전공필수 합 vs 졸업요건 (불일치는 경고만 — 원문 특성)
    major_req = sum(co["학점"] for co in CATALOG if co["이수구분"] == "전공필수")
    if major_req != GRADUATION["이수구분별_최소학점"]["전공필수"]:
        warns.append(
            f"명명 전공필수 합 {major_req}학점 ≠ 졸업요건 전공필수 {GRADUATION['이수구분별_최소학점']['전공필수']}학점. "
            f"(원문상 전공필수 과목 학점합과 졸업 최소요건이 다를 수 있음 — 원본 재확인 권장)"
        )

    return errs, warns


def main():
    errs, warns = validate()
    print("=== 검증 ===")
    if errs:
        print("❌ 오류:")
        for e in errs:
            print("  -", e)
    else:
        print("✅ 소계/중복 검증 통과")
    for w in warns:
        print("⚠️ ", w)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "course_catalog.json").write_text(
        json.dumps(CATALOG, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "graduation_requirements.json").write_text(
        json.dumps(GRADUATION, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 요약
    by_gubun = defaultdict(lambda: [0, 0])
    for co in CATALOG:
        by_gubun[co["이수구분"]][0] += 1
        by_gubun[co["이수구분"]][1] += co["학점"]
    print(f"\n=== 카탈로그 요약 (총 {len(CATALOG)}과목) ===")
    for g, (n, cr) in sorted(by_gubun.items()):
        print(f"  {g}: {n}과목 / {cr}학점")
    print("\n[저장] output/structured/course_catalog.json, graduation_requirements.json")


if __name__ == "__main__":
    main()
