"""AI Hub NL2SQL(Validation) → 난이도별 층화표본 eval_set.json 생성 (오프라인, 무료).

- VL.zip(라벨)에서 (db_id, hardness, utterance, gold query) 수집
- 난이도별 SAMPLES_PER_LEVEL 개 표본 (seed 고정), gold 가 실제로 실행되는 문항만 채택
- 해당 db_id 의 .sqlite 를 VS.zip 에서 bench/dbs/ 로 복사
- 각 문항의 스키마 DDL(sqlite_master) 을 함께 저장

실행:  uv run python -m bench.build_eval_set
"""
from __future__ import annotations

import json
import random
import sqlite3
import zipfile
from collections import defaultdict

from bench import config


def _load_labels() -> dict[str, list[dict]]:
    """VL.zip 에서 hardness → 레코드 리스트."""
    by_level: dict[str, list[dict]] = defaultdict(list)
    with zipfile.ZipFile(config.VAL_LABEL_ZIP) as z:
        for name in z.namelist():
            if not name.endswith(".json"):
                continue
            doc = json.loads(z.read(name).decode("utf-8"))
            for r in doc.get("data", []):
                by_level[r["hardness"]].append(
                    {"db_id": r["db_id"], "hardness": r["hardness"],
                     "question": r["utterance"], "gold_sql": r["query"]}
                )
    return by_level


def _sqlite_members() -> dict[str, str]:
    """VS.zip 안의 db_id → zip 멤버경로 (basename 이 ASCII 라 안전)."""
    out: dict[str, str] = {}
    with zipfile.ZipFile(config.VAL_SOURCE_ZIP) as z:
        for name in z.namelist():
            if name.endswith(".sqlite"):
                out[name.rsplit("/", 1)[-1][:-7]] = name
    return out


def _ensure_sqlite(db_id: str, member: str, zf: zipfile.ZipFile) -> "config.Path":
    dst = config.DB_DIR / f"{db_id}.sqlite"
    if not dst.exists():
        dst.write_bytes(zf.read(member))
    return dst


def _schema_ddl(db_path) -> str:
    con = sqlite3.connect(db_path)
    try:
        ddl = [r[0] for r in con.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL")]
    finally:
        con.close()
    return "\n".join(ddl)


def _gold_ok(sql: str, db_path) -> bool:
    con = sqlite3.connect(db_path)
    try:
        con.execute(sql).fetchall()
        return True
    except Exception:
        return False
    finally:
        con.close()


def main() -> None:
    config.DB_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(config.SEED)
    by_level = _load_labels()
    members = _sqlite_members()

    eval_records: list[dict] = []
    with zipfile.ZipFile(config.VAL_SOURCE_ZIP) as zf:
        for level in config.HARDNESS_ORDER:
            pool = by_level.get(level, [])
            rng.shuffle(pool)
            picked = 0
            for r in pool:
                if picked >= config.SAMPLES_PER_LEVEL:
                    break
                member = members.get(r["db_id"])
                if not member:
                    continue
                db_path = _ensure_sqlite(r["db_id"], member, zf)
                if not _gold_ok(r["gold_sql"], db_path):
                    continue  # gold 안 도는 문항은 EX 채점 불가 → 제외
                eval_records.append({
                    "id": f"{level.replace(' ', '_')}_{picked:03d}",
                    "db_id": r["db_id"],
                    "hardness": level,
                    "level_ko": config.HARDNESS_KO[level],
                    "question": r["question"],
                    "gold_sql": r["gold_sql"],
                    "schema": _schema_ddl(db_path),
                })
                picked += 1
            print(f"{config.HARDNESS_KO[level]}({level}): {picked}/{config.SAMPLES_PER_LEVEL} 채택 (풀 {len(pool)})")

    config.EVAL_SET.write_text(
        json.dumps(eval_records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n총 {len(eval_records)} 문항 → {config.EVAL_SET}")
    print(f"sqlite 복사본 → {config.DB_DIR} ({len(set(r['db_id'] for r in eval_records))} DB)")


if __name__ == "__main__":
    main()
