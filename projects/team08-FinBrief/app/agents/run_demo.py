"""Phase 0 관통 데모.  실행:  python -m app.agents.run_demo"""
from __future__ import annotations

from datetime import date

from .graph import graph


def main() -> None:
    init = {"run_id": "demo-001", "run_date": date.today().isoformat(),
            "status": "queued", "cards": [], "deliveries": [], "errors": []}
    final = graph.invoke(init)
    print(f"status={final['status']}  토픽 {len(final.get('unique_topics', []))} "
          f"→ 카드 {len(final.get('cards', []))} → 발송 {len(final.get('deliveries', []))} "
          f"(errors={len(final.get('errors', []))})")
    for c in final.get("cards", []):
        print(f"  [{c['topic_id']:7}] {c['headline']} | {c['lead']} (verified={c['verified']})")


if __name__ == "__main__":
    main()
