"""ingest_chroma 정규화·정합성 단위 테스트 (파트B — 실데이터 적재 전환).

임베딩·DB 없이 도는 순수 단위 테스트로, CI에서 항상 실행된다.
실제 CSV 정합성 검사는 "건수 확인"이 아니라 "이어붙인 데이터의 형식 검증 자동화"다:
사람이 data/raw/ CSV에 행을 추가한 뒤 pytest만 돌리면 형식 실수를 잡아낸다.
총 건수를 특정 숫자로 assert하지 않는다 — 행 이어붙이기가 정상 시나리오다.
"""

import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ingest_chroma import RAW_DIR, clean_answer, load_rows, normalize_row  # noqa: E402

EXPECTED_HEADER = [
    "대분류코드",
    "대분류명",
    "소분류코드",
    "소분류명",
    "백문일련번호",
    "주제",
    "질문",
    "답변",
    "원문링크",
]

SAMPLE_ROW = {
    "대분류코드": "84",
    "대분류명": "부동산/임대차",
    "소분류코드": "169",
    "소분류명": "주택임대차",
    "백문일련번호": "2482",
    "주제": "주택 이용 방법",
    "질문": "다른 사람의 주택을 이용하는 방법은 무엇인가요?",
    "답변": "전세권 설정과 임대차 계약 등이 있습니다.",
    "원문링크": "https://easylaw.go.kr/CSP/example",
}


def test_normalize_row_builds_expected_document():
    item = normalize_row(SAMPLE_ROW)
    assert item == {
        "id": "law_2482",
        "category": "부동산/임대차",  # 원문 그대로, "임대차"로 매핑하지 않는다
        "question": "다른 사람의 주택을 이용하는 방법은 무엇인가요?",
        "answer": "전세권 설정과 임대차 계약 등이 있습니다.",
        "subcategory": "주택임대차",
        "source_url": "https://easylaw.go.kr/CSP/example",
    }


def test_clean_answer_removes_table_marker_and_preserves_structure():
    raw = "◇ 지원 대상\n☞ 신청 방법은 다음과 같습니다.테이블 단락\n√ 유의사항"
    cleaned = clean_answer(raw)
    assert "테이블 단락" not in cleaned
    assert "◇" in cleaned
    assert "☞" in cleaned
    assert "√" in cleaned
    assert "\n" in cleaned  # 줄바꿈 보존


def test_raw_csv_integrity():
    # ① 1건 이상 로드됨 (건수 고정 금지)
    csv_paths = sorted(RAW_DIR.glob("*.csv"))
    assert csv_paths, "data/raw/ 에 CSV 파일이 있어야 한다"

    # ② 모든 CSV의 헤더가 9컬럼 명세와 일치
    for path in csv_paths:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == EXPECTED_HEADER, f"{path.name} 헤더 불일치"

    # load_rows는 id 중복·필수 필드 빈 값 발견 시 SystemExit를 던진다 (③④ 검사 포함)
    items = load_rows()
    assert len(items) >= 1

    # ③ id 전건 고유 (load_rows 통과로 보장되지만 명시적으로 재확인)
    ids = [item["id"] for item in items]
    assert len(ids) == len(set(ids))

    # ④ 필수 필드 빈 값 없음
    assert all(item["question"] and item["answer"] for item in items)

    # ⑤ source_url 전건 http(s):// 시작
    assert all(item["source_url"].startswith(("http://", "https://")) for item in items)
