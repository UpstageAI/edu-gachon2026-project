"""
Step 2. 재난문자 이력 전처리
입력: raw_data/disaster_messages_raw.json (fetch_all.py 결과)
출력: processed_data/disaster_messages.csv (Postgres COPY/적재용)

주요 처리:
1. SN 기준 중복 제거
2. RCPTN_RGN_NM -> region_sido / region_sigungu 분리
3. 날짜 필드 파싱 (CRT_DT, REG_YMD, MDFCN_YMD)
4. 실종경보 판별: DST_SE_NM == '기타' AND '182'(실종신고 전화) 포함
   -> is_missing_person=True로 표시 (물리적 삭제 아님, 통계 집계 시 WHERE 절로 제외)

실행: python preprocessors/preprocess_disaster_messages.py
"""
import json
import re
import os
import sys
from datetime import datetime

import pandas as pd

RAW_PATH = "raw_data/disaster_messages_raw.json"
OUT_PATH = "processed_data/disaster_messages.csv"

MISSING_PERSON_PHONE_PATTERN = re.compile(r"182")
MISSING_PERSON_KEYWORDS = ["실종", "배회", "찾습니다", "치매"]


def split_region(region_raw: str):
    """'경기도 김포시 ' -> ('경기도', '김포시')"""
    if not region_raw:
        return None, None
    parts = region_raw.strip().split()
    sido = parts[0] if len(parts) >= 1 else None
    sigungu = " ".join(parts[1:]) if len(parts) >= 2 else None
    return sido, sigungu


def parse_date(value: str, fmt: str):
    if not value:
        return None
    try:
        return datetime.strptime(value, fmt)
    except ValueError:
        return None


def is_missing_person(disaster_type: str, msg_content: str) -> bool:
    """
    DST_SE_NM이 '기타'인 것 중에서만 판별.
    (호우 등 실제 재난 카테고리에서 '실종'이 언급되는 경우는
     재난 상황 보고이므로 제외 대상이 아니라서 disaster_type=='기타'로 범위 한정)

    두 신호 중 하나라도 있으면 실종경보로 판별:
    1. 182(실종신고 전용전화) 포함
    2. 키워드(실종/배회/찾습니다/치매) 포함
       -> 182 대신 112(경찰 대표번호)로 안내되는 실종문자가 실제로 존재해서
          182 단독 체크로는 누락되는 케이스가 있었음 (해운대구 8월 사례에서 발견:
          "☎112"로 끝나는 실종자 수배 문자가 필터를 통과해 '기타' 통계에 잘못 포함됨)
    """
    if disaster_type != "기타":
        return False
    if MISSING_PERSON_PHONE_PATTERN.search(msg_content or ""):
        return True
    return any(kw in (msg_content or "") for kw in MISSING_PERSON_KEYWORDS)


def preprocess():
    if not os.path.exists(RAW_PATH):
        print(f"[ERROR] {RAW_PATH} 없음. 먼저 fetch_all.py로 전체 수집을 해야 합니다.")
        sys.exit(1)

    with open(RAW_PATH, "r", encoding="utf-8") as f:
        raw_items = json.load(f)

    print(f"원본 {len(raw_items)}건 로드")

    rows = []
    for item in raw_items:
        sn = item.get("SN")
        if sn is None:
            continue  # PK 없는 레코드는 스킵

        msg_content = (item.get("MSG_CN") or "").strip()
        region_raw = item.get("RCPTN_RGN_NM")
        sido, sigungu = split_region(region_raw)
        disaster_type = item.get("DST_SE_NM")

        rows.append({
            "sn": sn,
            "msg_content": msg_content,
            "region_raw": region_raw,
            "region_sido": sido,
            "region_sigungu": sigungu,
            "disaster_type": disaster_type,
            "emergency_step": item.get("EMRG_STEP_NM"),
            "created_at": parse_date(item.get("CRT_DT"), "%Y/%m/%d %H:%M:%S"),
            "reg_date": parse_date(item.get("REG_YMD"), "%Y-%m-%d"),
            "modified_date": parse_date(item.get("MDFCN_YMD"), "%Y-%m-%d"),
            "is_missing_person": is_missing_person(disaster_type, msg_content),
        })

    df = pd.DataFrame(rows)

    before = len(df)
    df = df.drop_duplicates(subset=["sn"])
    print(f"SN 중복 제거: {before}건 -> {len(df)}건")

    n_missing = df["is_missing_person"].sum()
    print(f"실종경보로 판별된 건수: {n_missing}건 ({n_missing/len(df)*100:.1f}%)")
    print("  -> 물리적으로 삭제하지 않고 is_missing_person=True로 표시함")
    print("  -> 통계 집계 쿼리에서는 WHERE is_missing_person = FALSE로 제외할 것")

    # 검증용: 실종경보로 판별된 것 중 샘플 5건 출력 (오탐 확인용)
    print("\n=== 실종경보 판별 샘플 (오탐 확인) ===")
    for msg in df[df["is_missing_person"]]["msg_content"].head(5):
        print(f"  - {msg[:60]}...")

    print("\n=== '기타'인데 실종경보로 판별 안 된 샘플 (누락 확인) ===")
    etc_not_missing = df[(df["disaster_type"] == "기타") & (~df["is_missing_person"])]
    for msg in etc_not_missing["msg_content"].head(5):
        print(f"  - {msg[:60]}...")

    os.makedirs("processed_data", exist_ok=True)
    df.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {OUT_PATH} ({len(df)}건)")

    print("\n=== 최종 disaster_type 분포 (실종경보 제외 시) ===")
    print(df[~df["is_missing_person"]]["disaster_type"].value_counts())


if __name__ == "__main__":
    preprocess()