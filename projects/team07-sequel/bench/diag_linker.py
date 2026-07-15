"""실 linker 진단 — 임베딩이 실제로 호출되는지, 무엇을 리턴하는지 직접 확인 (읽기전용, 1회성).

실행: uv run python -m bench.diag_linker
"""
import json
import random
import collections

from app.core import db, embeddings
from app.graph.nodes.query_normalizer import normalize
from app.graph.nodes.schema_linker import schema_link
from app.repositories import schema_repository
from bench import config

recs = json.loads(config.EVAL_SET.read_text(encoding="utf-8"))
random.seed(1)
sample = random.sample(recs, 8)

calls = {"n": 0}
orig = embeddings._embed
def counted(model, inputs):
    calls["n"] += 1
    return orig(model, inputs)
embeddings._embed = counted

how_counter = collections.Counter()

for rec in sample:
    db.set_target(str(config.DB_DIR / f"{rec['db_id']}.sqlite"))
    all_tables = schema_repository.list_tables()
    norm = normalize({"question": rec["question"]})
    linked = schema_link({"question": rec["question"], **norm})
    db.set_target(None)
    for h in linked["value_hints"]:
        how_counter[h["how"]] += 1
    print(f"[{rec['hardness']:10s}] DB테이블수={len(all_tables)} 링크된={len(linked['tables'])} "
          f"kw={norm['keywords']} hints={len(linked['value_hints'])} unresolved={linked['unresolved']}",
          flush=True)
    for h in linked["value_hints"]:
        print(f"    hint: {h}", flush=True)

print(f"\n임베딩 API 호출 횟수={calls['n']} (8문항 중, 0이면 진짜 안 불림)", flush=True)
print("value_hint how 분포:", dict(how_counter), flush=True)
