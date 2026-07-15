"""
Step 2. 재난대응기관(행정기관 코드) 전처리
입력: raw_data/response_agencies_raw.json
출력: processed_data/response_agencies.csv

주요 처리:
1. 전체 행 기준 중복 제거 (고유 ID 필드가 없어서)
2. disaster_messages의 region_sido/region_sigungu와 매칭할 수 있게
   whol_inst_nm 정리 (공백 정리)

실행: python preprocessors/preprocess_response_agencies.py
"""
import json
import os
import sys

import pandas as pd

RAW_PATH = "raw_data/response_agencies_raw.json"
OUT_PATH = "processed_data/response_agencies.csv"


def preprocess():
    if not os.path.exists(RAW_PATH):
        print(f"[ERROR] {RAW_PATH} 없음. 먼저 fetch_all.py로 수집해야 합니다.")
        sys.exit(1)

    with open(RAW_PATH, "r", encoding="utf-8") as f:
        raw_items = json.load(f)

    print(f"원본 {len(raw_items)}건 로드")

    rows = []
    for item in raw_items:
        rows.append({
            "cntrm_inst_cd": item.get("CNTRM_INST_CD"),
            "srch_type": item.get("SRCH_TYPE"),
            "sclsf_cd": item.get("SCLSF_CD"),
            "rnkn": item.get("RNKN"),
            "whol_inst_nm": (item.get("WHOL_INST_NM") or "").strip(),
            "inst_nm": (item.get("INST_NM") or "").strip(),
            "cycl": item.get("CYCL"),
            "hghrk_inst_cd": item.get("HGHRK_INST_CD"),
            "shghrk_inst_cd": item.get("SHGHRK_INST_CD"),
            "rprs_inst_cd": item.get("RPRS_INST_CD"),
            "lclsf_cd": item.get("LCLSF_CD"),
        })

    df = pd.DataFrame(rows)

    before = len(df)
    df = df.drop_duplicates()
    print(f"전체 행 기준 중복 제거: {before}건 -> {len(df)}건")

    # 참고 통계: 코드 분포 (재난유형 매핑 코드인지 확인용, 실제로는 행정기관 분류로 보임)
    print("\n=== lclsf_cd(대분류코드) 분포 ===")
    print(df["lclsf_cd"].value_counts())

    print("\n=== sclsf_cd(소분류코드) 분포 (상위 10개) ===")
    print(df["sclsf_cd"].value_counts().head(10))

    os.makedirs("processed_data", exist_ok=True)
    df.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {OUT_PATH} ({len(df)}건)")


if __name__ == "__main__":
    preprocess()