"""
Step 0.5. 재난문자 데이터의 실제 카테고리 분포 확인.
- DST_SE_NM (재해구분): 실종경보를 어떻게 필터링할지 확인용
- EMRG_STEP_NM (긴급단계): 값 종류 확인용
큰 수집 전에 실행해서 필터링 기준을 정하는 목적.

실행: python fetchers/explore_categories.py [총 조회건수(기본 2000)]
"""
import sys
import os
from collections import Counter

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from config import DATASETS


def explore(sample_size: int = 2000, page_size: int = 1000):
    info = DATASETS["disaster_messages"]
    dst_counter = Counter()
    step_counter = Counter()
    missing_person_keywords = ["실종", "배회", "찾습니다", "치매"]
    keyword_hits = Counter()

    collected = 0
    page_no = 1

    while collected < sample_size:
        params = {
            "serviceKey": info["service_key"],
            "pageNo": page_no,
            "numOfRows": page_size,
            "returnType": "json",
        }
        resp = requests.get(info["endpoint"], params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        header = data.get("header", {})
        if header.get("resultCode") != "00":
            print(f"[ERROR] {header}")
            break

        body = data.get("body", [])
        if not body:
            break

        for item in body:
            dst_counter[item.get("DST_SE_NM")] += 1
            step_counter[item.get("EMRG_STEP_NM")] += 1
            msg = item.get("MSG_CN", "")
            for kw in missing_person_keywords:
                if kw in msg:
                    keyword_hits[(item.get("DST_SE_NM"), kw)] += 1

        collected += len(body)
        page_no += 1
        print(f"누적 {collected}건 확인...")

    print("\n=== DST_SE_NM (재해구분) 분포 ===")
    for k, v in dst_counter.most_common():
        print(f"  {k}: {v}건")

    print("\n=== EMRG_STEP_NM (긴급단계) 분포 ===")
    for k, v in step_counter.most_common():
        print(f"  {k}: {v}건")

    print("\n=== 실종/배회 키워드가 어떤 DST_SE_NM에 몰려있는지 ===")
    for (dst, kw), v in keyword_hits.most_common(20):
        print(f"  DST_SE_NM='{dst}' + 키워드='{kw}': {v}건")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    explore(n)