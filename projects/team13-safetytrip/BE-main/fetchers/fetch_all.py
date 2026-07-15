"""
Step 1. 전체 데이터 수집 (페이징 처리 포함)
inspect_schema.py로 실제 응답 구조를 확인한 뒤 아래 파싱 부분을 실제 필드명에 맞게 수정할 것.

실행: python fetchers/fetch_all.py <dataset_key>
예:   python fetchers/fetch_all.py disaster_messages
"""
import json
import sys
import os
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from config import DATASETS


def _probe_page_size(info: dict, requested_size: int) -> int:
    """
    실제로 요청한 numOfRows만큼 안전하게 받아올 수 있는지 1번만 테스트.
    잘려서 온다면(offset 밀림으로 데이터 유실 위험) 검증된 안전값(100)으로 자동 축소.
    """
    params = {
        "serviceKey": info["service_key"],
        "pageNo": 1,
        "numOfRows": requested_size,
        "returnType": "json",
    }
    try:
        resp = requests.get(info["endpoint"], params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        print(f"[WARN] probe 요청 실패({e}). 안전값 100으로 진행합니다.")
        return 100

    actual = len(_extract_items(data))
    print(f"probe: numOfRows={requested_size} 요청 -> 실제 {actual}건 수신")

    if actual >= requested_size:
        print(f"  -> 안전함. numOfRows={requested_size}로 진행합니다.")
        return requested_size

    print("  -> [WARN] 요청보다 적게 옴 (잘림 위험, offset 밀려서 데이터 유실 가능).")
    print("  -> 검증된 안전값 numOfRows=100으로 자동 축소합니다.")
    return 100


def fetch_all(dataset_key: str, page_size: int = 100, max_pages: int = 2000):
    info = DATASETS[dataset_key]

    if not info["service_key"]:
        print(f"[ERROR] {info['name']}: 서비스키가 .env에 없습니다.")
        return []

    # 요청한 page_size가 100보다 크면(더 큰 값을 시도하려는 의도) 먼저 안전한지 검증
    if page_size > 100:
        page_size = _probe_page_size(info, page_size)

    all_items = []
    seen_sns = set()  # 중복 방지용 (SN 기준)
    empty_retry_count = 0
    MAX_EMPTY_RETRIES = 3
    total_count_reported = None

    page_no = 1
    while page_no <= max_pages:
        params = {
            "serviceKey": info["service_key"],
            "pageNo": page_no,
            "numOfRows": page_size,
            "returnType": "json",
        }

        try:
            resp = requests.get(info["endpoint"], params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] page {page_no} 요청 실패: {e}")
            print("  -> 3초 대기 후 같은 페이지 재시도")
            time.sleep(3)
            continue  # page_no 증가 없이 같은 페이지 재시도

        header = data.get("header", {})
        if header.get("resultCode") != "00":
            print(f"[ERROR] API 오류: {header.get('resultMsg')} / {header.get('errorMsg')}")
            print("  -> 3초 대기 후 같은 페이지 재시도")
            time.sleep(3)
            continue

        if total_count_reported is None:
            total_count_reported = data.get("totalCount")
            print(f"API가 보고한 totalCount: {total_count_reported}")

        items = _extract_items(data)

        if not items:
            empty_retry_count += 1
            if empty_retry_count > MAX_EMPTY_RETRIES:
                print(f"page {page_no}: {MAX_EMPTY_RETRIES}회 재시도해도 데이터 없음. 진짜 종료로 판단.")
                break
            print(f"page {page_no}: 빈 응답 (재시도 {empty_retry_count}/{MAX_EMPTY_RETRIES}) - 2초 대기 후 재시도")
            time.sleep(2)
            continue  # page_no 증가 없이 재시도

        empty_retry_count = 0  # 성공했으니 재시도 카운터 리셋

        # SN 기준 중복 제거하면서 추가
        new_count = 0
        for item in items:
            sn = item.get("SN")
            if sn is not None and sn in seen_sns:
                continue
            if sn is not None:
                seen_sns.add(sn)
            all_items.append(item)
            new_count += 1

        print(f"page {page_no}: {len(items)}건 수신 (신규 {new_count}건, 누적 {len(all_items)}건 / totalCount={total_count_reported})")

        # 종료 판단: totalCount 대비 다 모았으면 종료
        # (반환 건수가 요청보다 적어도 아직 안 끝났을 수 있으므로 이걸로만 판단하지 않음)
        if total_count_reported and len(all_items) >= total_count_reported:
            print("totalCount만큼 다 모았습니다. 종료.")
            break

        # 이번 페이지에서 신규 데이터가 하나도 없었다면(전부 중복) 종료 신호로 취급
        if new_count == 0:
            print("이번 페이지에 신규 데이터 없음 (전부 중복). 종료.")
            break

        page_no += 1
        time.sleep(0.2)  # API 과호출 방지

    os.makedirs("raw_data", exist_ok=True)
    out_path = info["output_raw"]
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False, indent=2)

    print(f"\n총 {len(all_items)}건 저장 완료 -> {out_path}")

    if total_count_reported and len(all_items) < total_count_reported:
        print(f"[WARN] totalCount({total_count_reported})보다 적게 모였습니다. "
              f"데이터 유실 가능성이 있으니 확인이 필요합니다.")

    return all_items


def _extract_items(data: dict):
    """
    실제 응답 구조 확인 결과: body가 바로 items 배열임.
    {"header": {...}, "numOfRows": N, "pageNo": N, "totalCount": N, "body": [ {...}, ... ]}
    """
    body = data.get("body")
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        return body.get("items", [])
    return []


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in DATASETS:
        print(f"사용법: python fetch_all.py <{'|'.join(DATASETS.keys())}> [numOfRows]")
        sys.exit(1)

    requested_page_size = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    fetch_all(sys.argv[1], page_size=requested_page_size)