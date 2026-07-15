"""
Step 0. 각 API를 1페이지만 호출해서 실제 응답 구조(필드명, 페이징 방식)를 확인.
전처리 로직을 짜기 전에 반드시 먼저 실행해서 결과를 확인할 것.

실행: python fetchers/inspect_schema.py
"""
import json
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from config import DATASETS

def inspect(dataset_key: str):
    info = DATASETS[dataset_key]

    if not info["service_key"]:
        print(f"[SKIP] {info['name']}: 서비스키가 .env에 없음")
        return

    params = {
        "serviceKey": info["service_key"],
        "pageNo": 1,
        "numOfRows": 3,  # 스키마 확인용이라 3건만
        "returnType": "json",
    }

    print(f"\n{'='*60}")
    print(f"[{info['name']}] {info['endpoint']}")
    print(f"{'='*60}")

    try:
        resp = requests.get(info["endpoint"], params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])

        # 확인용 저장
        os.makedirs("raw_data", exist_ok=True)
        sample_path = f"raw_data/{dataset_key}_sample.json"
        with open(sample_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n-> 샘플 저장됨: {sample_path}")

    except requests.exceptions.RequestException as e:
        print(f"[ERROR] 요청 실패: {e}")
    except json.JSONDecodeError:
        print("[ERROR] JSON 파싱 실패. 응답 원문(앞부분):")
        print(resp.text[:1000])


if __name__ == "__main__":
    # 인자로 특정 데이터셋만 지정 가능. 없으면 전체 실행.
    # 예: python inspect_schema.py disaster_messages
    targets = sys.argv[1:] if len(sys.argv) > 1 else list(DATASETS.keys())

    for key in targets:
        if key not in DATASETS:
            print(f"[ERROR] 알 수 없는 데이터셋: {key}")
            continue
        inspect(key)