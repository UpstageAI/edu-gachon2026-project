"""zero-shot eval_set.json 의 각 문항에 same-db few-shot 예시를 붙여 eval_set_fewshot.json 생성.

- 예시 출처: 같은 db_id 의 다른 validation 질문 (train∩val=0 이라 train 사용 불가).
  타깃 질문 자신은 제외(leave-one-out). 실전 = 자사 DB 과거 쿼리 검색 시나리오.
- 검색: 같은 db_id 후보 중 질문 char-bigram Jaccard 유사도 top-K (무료·결정적).

실행:  uv run python -m bench.build_fewshot
"""
from __future__ import annotations

import json
import zipfile
from collections import defaultdict

from bench import config


def _bigrams(s: str) -> set[str]:
    s = "".join(s.split())
    return {s[i:i + 2] for i in range(len(s) - 1)} or {s}


def _sim(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if (a or b) else 0.0


def _val_pool_by_db() -> dict[str, list[dict]]:
    pool: dict[str, list[dict]] = defaultdict(list)
    with zipfile.ZipFile(config.VAL_LABEL_ZIP) as z:
        for name in z.namelist():
            if name.endswith(".json"):
                for r in json.loads(z.read(name).decode("utf-8")).get("data", []):
                    pool[r["db_id"]].append({"question": r["utterance"], "sql": r["query"]})
    return pool


def main() -> None:
    targets = json.loads(config.EVAL_SET.read_text(encoding="utf-8"))
    pool = _val_pool_by_db()

    out = []
    empty = 0
    for t in targets:
        tgt_bg = _bigrams(t["question"])
        cands = [
            c for c in pool.get(t["db_id"], [])
            if not (c["question"] == t["question"] and c["sql"] == t["gold_sql"])  # 자기 제외
        ]
        cands.sort(key=lambda c: _sim(tgt_bg, _bigrams(c["question"])), reverse=True)
        shots = cands[: config.FEWSHOT_K]
        if not shots:
            empty += 1
        out.append({**t, "fewshot": shots})

    config.EVAL_SET_FEWSHOT.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    avg = sum(len(r["fewshot"]) for r in out) / len(out)
    print(f"{len(out)} 문항 → {config.EVAL_SET_FEWSHOT}")
    print(f"평균 예시 {avg:.1f}개/문항 (K={config.FEWSHOT_K}), 예시 0개 문항 {empty}개")


if __name__ == "__main__":
    main()
