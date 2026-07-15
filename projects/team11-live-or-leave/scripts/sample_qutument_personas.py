"""Sample QUTUMENT Nemotron-Personas-Korea Extended without full download.

The script reads the remote Parquet file through Hugging Face's resolved URL
and stores small CSV samples for scenario design.

Examples:
  .venv/bin/python scripts/sample_qutument_personas.py probe --rows 50
  .venv/bin/python scripts/sample_qutument_personas.py sample --target 500
  .venv/bin/python scripts/sample_qutument_personas.py sample --target 3000 \
      --output data/personas/persona_sample_stratified.csv
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from huggingface_hub import HfFileSystem
import pyarrow.parquet as pq
from pyarrow.fs import FSSpecHandler, PyFileSystem


REPO_ID = "QUTUMENT/nemotron-personas-korea-extended"
PARQUET_PATH = "data/ko_KR.parquet"
DEFAULT_OUTPUT_DIR = Path("data/personas")

PREFERRED_COLUMNS = [
    "uuid",
    "age",
    "sex",
    "marital_status",
    "family_type",
    "housing_type",
    "housing_tenure",
    "occupation",
    "employment_status",
    "economic_activity_status",
    "income_bracket",
    "district",
    "province",
    "country",
    "persona",
    "professional_persona",
    "family_persona",
    "healthcare_persona",
    "financial_persona",
    "detailed_persona",
    "hobbies_and_interests",
    "hobbies_and_interests_list",
    "cultural_background",
    "health_status",
    "physical_health",
    "mental_health",
    "bmi_status",
    "blood_pressure_status",
    "blood_sugar_status",
    "waist_status",
    "smoking_status",
    "drinking_status",
    "extraversion",
    "agreeableness",
    "conscientiousness",
    "neuroticism",
    "openness",
]

LOCATION_FIELDS = ("province", "district", "country")
STRATA_FIELDS = (
    "age_group",
    "family_type",
    "occupation_group",
    "housing_group",
    "income_group",
)


@dataclass
class ParquetSource:
    parquet_file: pq.ParquetFile
    columns: list[str]


def build_source() -> ParquetSource:
    hf_fs = HfFileSystem()
    arrow_fs = PyFileSystem(FSSpecHandler(hf_fs))
    path = f"datasets/{REPO_ID}/{PARQUET_PATH}"
    parquet_file = pq.ParquetFile(path, filesystem=arrow_fs)
    return ParquetSource(
        parquet_file=parquet_file,
        columns=list(parquet_file.schema_arrow.names),
    )


def select_columns(all_columns: list[str], include_all: bool = False) -> list[str]:
    if include_all:
        return all_columns

    selected = [col for col in PREFERRED_COLUMNS if col in all_columns]
    if not selected:
        return all_columns

    # Always keep any explicit persona text fields if the extension uses a
    # slightly different naming convention.
    selected_set = set(selected)
    for col in all_columns:
        lower = col.lower()
        if "persona" in lower or lower in LOCATION_FIELDS:
            selected_set.add(col)
    return [col for col in all_columns if col in selected_set]


def read_row_group(
    source: ParquetSource,
    row_group_index: int,
    columns: list[str],
) -> pd.DataFrame:
    table = source.parquet_file.read_row_group(row_group_index, columns=columns)
    return table.to_pandas()


def iter_batches(
    source: ParquetSource,
    columns: list[str],
    *,
    shuffle_row_groups: bool,
    seed: int,
) -> Iterable[pd.DataFrame]:
    indices = list(range(source.parquet_file.num_row_groups))
    if shuffle_row_groups:
        random.Random(seed).shuffle(indices)
    for idx in indices:
        yield read_row_group(source, idx, columns)


def is_seoulish(row: dict[str, Any]) -> bool:
    values = [str(row.get(field, "")) for field in LOCATION_FIELDS]
    joined = " ".join(values).lower()
    return "서울" in joined or "seoul" in joined


def normalize_text(value: Any, fallback: str = "unknown") -> str:
    if value is None:
        return fallback
    if isinstance(value, float) and math.isnan(value):
        return fallback
    text = str(value).strip()
    return text if text else fallback


def age_group(value: Any) -> str:
    try:
        age = int(value)
    except (TypeError, ValueError):
        return "unknown"
    if age < 20:
        return "under_20"
    if age < 30:
        return "20s"
    if age < 40:
        return "30s"
    if age < 50:
        return "40s"
    if age < 60:
        return "50s"
    if age < 70:
        return "60s"
    return "70_plus"


def coarse_occupation(value: Any) -> str:
    text = normalize_text(value)
    if any(token in text for token in ("학생", "대학생", "대학원")):
        return "student"
    if any(token in text for token in ("회사", "사무", "관리", "전문", "연구", "개발", "교사")):
        return "office_professional"
    if any(token in text for token in ("서비스", "판매", "영업", "매장", "상담")):
        return "service_sales"
    if any(token in text for token in ("자영", "사업", "프리랜서")):
        return "self_employed_freelance"
    if any(token in text for token in ("은퇴", "무직", "주부")):
        return "not_employed_care"
    if any(token in text for token in ("생산", "기술", "운전", "건설", "현장")):
        return "field_technical"
    return text[:40]


def coarse_housing(value: Any) -> str:
    text = normalize_text(value)
    if "아파트" in text:
        return "apartment"
    if "오피스텔" in text:
        return "officetel"
    if any(token in text for token in ("다세대", "다가구", "연립", "빌라")):
        return "multi_family"
    if "단독" in text:
        return "detached"
    return text[:40]


def coarse_income(row: dict[str, Any]) -> str:
    for col in ("income_bracket", "income_group", "household_income", "personal_income"):
        if col in row:
            return normalize_text(row.get(col))
    return "unknown"


def add_derived_fields(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["age_group"] = age_group(row.get("age"))
    out["occupation_group"] = coarse_occupation(row.get("occupation"))
    out["housing_group"] = coarse_housing(row.get("housing_type"))
    out["income_group"] = coarse_income(row)
    out["is_seoulish"] = is_seoulish(row)
    return out


def row_key(row: dict[str, Any]) -> str:
    uuid = normalize_text(row.get("uuid"), "")
    if uuid:
        return uuid
    payload = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def stratum_key(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(normalize_text(row.get(field)) for field in STRATA_FIELDS)


def collect_sample(
    source: ParquetSource,
    *,
    target: int,
    columns: list[str],
    seed: int,
    seoul_only: bool,
    min_per_stratum: int,
    max_scan_rows: int,
) -> list[dict[str, Any]]:
    randomizer = random.Random(seed)
    selected: list[dict[str, Any]] = []
    selected_keys: set[str] = set()
    stratum_counts: Counter[tuple[str, ...]] = Counter()
    fallback_pool: list[dict[str, Any]] = []
    scanned = 0

    for batch in iter_batches(source, columns, shuffle_row_groups=True, seed=seed):
        records = batch.to_dict(orient="records")
        randomizer.shuffle(records)
        for raw in records:
            scanned += 1
            row = add_derived_fields(raw)
            if seoul_only and not row["is_seoulish"]:
                continue
            key = row_key(row)
            if key in selected_keys:
                continue

            skey = stratum_key(row)
            if stratum_counts[skey] < min_per_stratum:
                selected.append(row)
                selected_keys.add(key)
                stratum_counts[skey] += 1
            else:
                fallback_pool.append(row)

            if len(selected) >= target:
                return selected[:target]
            if scanned >= max_scan_rows:
                break
        if len(selected) >= target or scanned >= max_scan_rows:
            break

    randomizer.shuffle(fallback_pool)
    for row in fallback_pool:
        if len(selected) >= target:
            break
        key = row_key(row)
        if key in selected_keys:
            continue
        selected.append(row)
        selected_keys.add(key)
    return selected[:target]


def write_csv(rows: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        output.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def top(field: str, limit: int = 12) -> list[tuple[str, int]]:
        return Counter(normalize_text(row.get(field)) for row in rows).most_common(limit)

    return {
        "rows": len(rows),
        "seoulish_rows": sum(1 for row in rows if row.get("is_seoulish")),
        "age_group": top("age_group"),
        "family_type": top("family_type"),
        "occupation_group": top("occupation_group"),
        "housing_group": top("housing_group"),
        "income_group": top("income_group"),
        "province": top("province"),
        "district": top("district"),
    }


def write_schema_notes(
    *,
    source: ParquetSource,
    rows: list[dict[str, Any]],
    output: Path,
    selected_columns: list[str],
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    summary = summarize(rows)
    lines = [
        "# QUTUMENT Persona Schema Probe",
        "",
        f"- Dataset: `{REPO_ID}`",
        f"- File: `{PARQUET_PATH}`",
        f"- Total columns found: {len(source.columns)}",
        f"- Probe rows: {len(rows)}",
        f"- Selected columns read: {len(selected_columns)}",
        "",
        "## Columns",
        "",
    ]
    lines.extend(f"- `{col}`" for col in source.columns)
    lines.extend([
        "",
        "## Probe Summary",
        "",
        "```json",
        json.dumps(summary, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Questions For Scenario Design",
        "",
        "- Which persona groups should be emphasized in the final presentation?",
        "- Should rent/ownership and commute-time requirements be mocked or excluded from MVP?",
        "- Which missing-data categories should be treated as follow-up data collection?",
    ])
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def command_probe(args: argparse.Namespace) -> None:
    source = build_source()
    columns = select_columns(source.columns, include_all=args.all_columns)
    rows: list[dict[str, Any]] = []
    for batch in iter_batches(source, columns, shuffle_row_groups=False, seed=args.seed):
        for raw in batch.head(args.rows - len(rows)).to_dict(orient="records"):
            rows.append(add_derived_fields(raw))
        if len(rows) >= args.rows:
            break

    write_csv(rows, args.output)
    write_schema_notes(
        source=source,
        rows=rows,
        output=args.notes,
        selected_columns=columns,
    )
    print(json.dumps({
        "output": str(args.output),
        "notes": str(args.notes),
        "columns_found": len(source.columns),
        "columns_read": len(columns),
        "summary": summarize(rows),
    }, ensure_ascii=False, indent=2))


def command_sample(args: argparse.Namespace) -> None:
    source = build_source()
    columns = select_columns(source.columns, include_all=args.all_columns)
    rows = collect_sample(
        source,
        target=args.target,
        columns=columns,
        seed=args.seed,
        seoul_only=args.seoul_only,
        min_per_stratum=args.min_per_stratum,
        max_scan_rows=args.max_scan_rows,
    )
    write_csv(rows, args.output)
    summary_path = args.output.with_suffix(".summary.json")
    summary_path.write_text(
        json.dumps(summarize(rows), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(args.output),
        "summary": str(summary_path),
        "columns_read": len(columns),
        "summary_data": summarize(rows),
    }, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe = subparsers.add_parser("probe", help="Read a small schema/sample probe")
    probe.add_argument("--rows", type=int, default=50)
    probe.add_argument("--seed", type=int, default=42)
    probe.add_argument("--all-columns", action="store_true")
    probe.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "persona_sample_probe.csv",
    )
    probe.add_argument(
        "--notes",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "persona_schema_notes.md",
    )
    probe.set_defaults(func=command_probe)

    sample = subparsers.add_parser("sample", help="Create a Seoul-focused sample")
    sample.add_argument("--target", type=int, default=500)
    sample.add_argument("--seed", type=int, default=42)
    sample.add_argument("--all-columns", action="store_true")
    sample.add_argument("--seoul-only", action=argparse.BooleanOptionalAction, default=True)
    sample.add_argument("--min-per-stratum", type=int, default=2)
    sample.add_argument("--max-scan-rows", type=int, default=250_000)
    sample.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "persona_sample_500.csv",
    )
    sample.set_defaults(func=command_sample)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
