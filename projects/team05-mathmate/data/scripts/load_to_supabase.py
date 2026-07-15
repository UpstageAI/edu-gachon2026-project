"""
data/scripts/load_to_supabase.py — 문제은행(problems.json)을 Supabase에 적재.

- 원본은 data/problems.json (파이프라인이 만드는 깨끗한 원본. CSV의 엑셀 가공값 아님).
- hint_by_level {"1","2","3"} → hint1/hint2/hint3 컬럼으로 변환.
- id 기준 upsert → 여러 번 돌려도 중복 없이 갱신.
- service_role 키가 필요(RLS 우회). .env의 SUPABASE_SERVICE_KEY 사용.

실행 (프로젝트 루트, venv 활성화 상태):
  python data/scripts/load_to_supabase.py
  python data/scripts/load_to_supabase.py --file data/problems.json --batch 500
"""
import argparse
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from app.core import config  # noqa: E402


def _rows(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    rows = []
    for p in data:
        h = p.get("hint_by_level", {}) or {}
        rows.append({
            "id": p["id"],
            "grade": p.get("grade"),
            "semester": p.get("semester"),
            "unit": p.get("unit"),
            "difficulty": p.get("difficulty"),
            "problem": p["problem"],
            "answer": str(p["answer"]),
            "hint1": h.get("1", ""),
            "hint2": h.get("2", ""),
            "hint3": h.get("3", ""),
            "solution_steps": list(p.get("solution_steps", [])),
            "next_question": p.get("next_question", ""),
            "source": p.get("source", ""),
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=os.path.join(ROOT, "data", "problems.json"))
    ap.add_argument("--batch", type=int, default=500)
    args = ap.parse_args()

    if not config.SUPABASE_URL:
        print("[에러] .env에 SUPABASE_URL이 없습니다."); sys.exit(1)
    if not config.SUPABASE_SERVICE_KEY or "붙여넣기" in config.SUPABASE_SERVICE_KEY:
        print("[에러] .env의 SUPABASE_SERVICE_KEY에 service_role 키를 넣어주세요.\n"
              "       Supabase 대시보드 > Project Settings > API > service_role 값."); sys.exit(1)

    try:
        from supabase import create_client
    except ImportError:
        print("[에러] supabase 패키지가 없습니다.  pip install supabase --break-system-packages"); sys.exit(1)

    client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
    rows = _rows(args.file)
    print(f"적재 대상 {len(rows)}개 ({args.file})")

    done = 0
    for i in range(0, len(rows), args.batch):
        chunk = rows[i:i + args.batch]
        client.table("problems").upsert(chunk, on_conflict="id").execute()
        done += len(chunk)
        print(f"  upsert {done}/{len(rows)}")

    # 실제 저장 개수 확인
    res = client.table("problems").select("id", count="exact").execute()
    print(f"완료. Supabase problems 테이블 총 {res.count}개")


if __name__ == "__main__":
    main()
