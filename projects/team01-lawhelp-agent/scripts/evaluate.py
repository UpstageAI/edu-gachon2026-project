"""파이프라인 정량 평가 스크립트 (파트B 평가실행 작업지시).

data/eval_golden_set.json 75문항을 로컬 서버의 POST /chat/sync로 순차 호출해
축 1(가드레일)·축 2(구간 라우팅)·축 3(Hit@3)을 채점하고, distance 분포와
임계값 제안(r1), 축 4 사람 채점용 표본 파일을 생성한다.

전제·주의:
- 로컬 uvicorn(localhost:8000)이 떠 있어야 한다. 1회 실행 = 실 LLM 최대 75회 호출.
- pytest/CI에서 실행하지 않는다 (실비용·실시간).
- 채점 기준 문자열·구간 매핑은 골든셋의 pipeline_contract 메타에서 읽는다 (하드코딩 금지).

사용법:
  python scripts/evaluate.py --round r1     # 1차 (현행 임계값)
  python scripts/evaluate.py --round final  # 2차 (승인된 임계값 반영 후)

산출물 (프로젝트 루트):
  eval_raw_results_{round}.json  문항별 원시 응답
  eval_report_{round}.md         채점 리포트 (r1: 임계값 제안 / final: r1 대비 변화)
  eval_axis4_samples.md          축 4 사람 채점용 표본
"""

import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.routing import (  # noqa: E402
    EXACT_DISTANCE_THRESHOLD,
    RELATED_DISTANCE_THRESHOLD,
)

GOLDEN_SET_PATH = PROJECT_ROOT / "data" / "eval_golden_set.json"
API_BASE = os.environ.get("API_BASE_URL", "http://localhost:8000")
REQUEST_TIMEOUT_SECONDS = 60

AXIS3_TYPE_ORDER = ("원문형", "생활어형", "광의형")
ZONE1_SAMPLE_PLAN = (("원문형", 2), ("생활어형", 2), ("광의형", 1))


# ---------------------------------------------------------------- 호출


def run_calls(items: list[dict]) -> list[dict]:
    """75문항을 순서대로 호출한다. 재시도 없음, 문항당 60초 타임아웃."""
    records = []
    for index, item in enumerate(items, start=1):
        response_data = None
        http_error = None
        try:
            response = requests.post(
                f"{API_BASE}/chat/sync",
                json={"message": item["question"]},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            response_data = response.json()
        except Exception as exc:
            http_error = f"{type(exc).__name__}: {exc}"
        records.append({"item": item, "response": response_data, "http_error": http_error})
        status = http_error or (response_data or {}).get("response_type", "?")
        print(f"[{index:2d}/{len(items)}] {item['id']} → {status}")
    return records


# ---------------------------------------------------------------- 공통 헬퍼


def is_measured(record: dict) -> bool:
    """측정 실패(HTTP 오류 또는 LLM error 폴백) 여부 — 채점 분모에서 제외."""
    if record["http_error"]:
        return False
    return record["response"].get("response_type") != "error"


def actual_blocked(response: dict) -> bool:
    return bool(response.get("guardrail_blocked")) or response.get("response_type") == "out_of_scope"


def top1_distance(response: dict):
    top_documents = response.get("top_documents") or []
    return top_documents[0]["distance"] if top_documents else None


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def distribution_row(values: list[float]) -> str:
    if not values:
        return "- | - | - | - | - | 0"
    cells = [percentile(values, p) for p in (0, 25, 50, 75, 100)]
    return " | ".join(f"{value:.4f}" for value in cells) + f" | {len(values)}"


def block_message_kind(answer: str, fixed_strings: dict) -> str:
    if fixed_strings.get("scope_check_block", "") in answer:
        return "scope_check_block"
    if fixed_strings.get("domain_block", "") in answer:
        return "domain_block"
    return "기타문구"


# ---------------------------------------------------------------- 채점


def score_axis1(measured: list[dict], fixed_strings: dict) -> dict:
    expected_block = [r for r in measured if r["item"]["expected_guardrail"] == "block"]
    expected_pass = [r for r in measured if r["item"]["expected_guardrail"] == "pass"]

    blocked_ok = [r for r in expected_block if actual_blocked(r["response"])]
    over_blocked = [r for r in expected_pass if actual_blocked(r["response"])]

    over_block_by_type: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [차단수, 전체수]
    for record in expected_pass:
        entry = over_block_by_type[record["item"]["question_type"]]
        entry[1] += 1
        if actual_blocked(record["response"]):
            entry[0] += 1

    blocked_detail = []
    for record in expected_block:
        response = record["response"]
        blocked_detail.append(
            {
                "id": record["item"]["id"],
                "question": record["item"]["question"],
                "blocked": actual_blocked(response),
                "message_kind": block_message_kind(response.get("answer", ""), fixed_strings)
                if actual_blocked(response)
                else "-",
                "expected_block_message": record["item"].get("expected_block_message", "-"),
            }
        )

    return {
        "block_total": len(expected_block),
        "block_hit": len(blocked_ok),
        "pass_total": len(expected_pass),
        "over_block": len(over_blocked),
        "over_block_items": [
            {
                "id": r["item"]["id"],
                "question": r["item"]["question"],
                "question_type": r["item"]["question_type"],
                "message_kind": block_message_kind(r["response"].get("answer", ""), fixed_strings),
            }
            for r in over_blocked
        ],
        "over_block_by_type": dict(over_block_by_type),
        "blocked_detail": blocked_detail,
    }


def score_axis2(measured: list[dict], zone_mapping: dict) -> dict:
    eligible = []  # 기대 pass이고 실제로도 통과한 문항
    mismatched_guardrail = []
    for record in measured:
        if record["item"]["expected_guardrail"] != "pass":
            continue
        if actual_blocked(record["response"]):
            mismatched_guardrail.append(record)
        else:
            eligible.append(record)

    confusion: Counter = Counter()
    mismatches = []
    for record in eligible:
        expected_zone = record["item"]["expected_zone"]
        actual_zone = zone_mapping.get(record["response"].get("response_type"))
        confusion[(expected_zone, actual_zone)] += 1
        if expected_zone != actual_zone:
            mismatches.append(
                {
                    "id": record["item"]["id"],
                    "question": record["item"]["question"],
                    "expected": expected_zone,
                    "actual": actual_zone,
                    "top1_distance": top1_distance(record["response"]),
                }
            )

    correct = sum(count for (expected, actual), count in confusion.items() if expected == actual)
    fatal_1_to_23 = sum(
        count for (expected, actual), count in confusion.items() if expected == 1 and actual in (2, 3)
    )
    fatal_3_to_1 = sum(
        count for (expected, actual), count in confusion.items() if expected == 3 and actual == 1
    )

    return {
        "eligible": len(eligible),
        "correct": correct,
        "confusion": confusion,
        "mismatches": mismatches,
        "fatal_1_to_23": fatal_1_to_23,
        "fatal_3_to_1": fatal_3_to_1,
        "guardrail_mismatch": [
            {"id": r["item"]["id"], "question": r["item"]["question"], "question_type": r["item"]["question_type"]}
            for r in mismatched_guardrail
        ],
    }


def score_axis3(measured: list[dict]) -> dict:
    targets = [r for r in measured if r["item"]["expected_doc_ids"]]
    unevaluated = []  # 차단되어 top_documents가 빈 문항 (분모 제외)
    hits, misses = [], []
    by_type: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [hit, total]

    for record in targets:
        response = record["response"]
        top_ids = [doc["id"] for doc in response.get("top_documents") or []]
        if not top_ids:
            unevaluated.append({"id": record["item"]["id"], "question": record["item"]["question"]})
            continue
        expected_ids = set(record["item"]["expected_doc_ids"])
        hit = bool(expected_ids & set(top_ids))
        entry = by_type[record["item"]["question_type"]]
        entry[1] += 1
        if hit:
            entry[0] += 1
            hits.append(record)
        else:
            misses.append(
                {
                    "id": record["item"]["id"],
                    "question": record["item"]["question"],
                    "question_type": record["item"]["question_type"],
                    "expected": sorted(expected_ids),
                    "actual_top3": top_ids,
                }
            )

    evaluated = len(targets) - len(unevaluated)
    return {
        "target_total": len(targets),
        "evaluated": evaluated,
        "hit": len(hits),
        "by_type": dict(by_type),
        "misses": misses,
        "unevaluated": unevaluated,
    }


def collect_distance_distribution(measured: list[dict]) -> dict:
    by_type: dict[str, list[float]] = defaultdict(list)
    zone1_expected: list[float] = []
    irrelevant: list[float] = []  # 무관키워드형 + 기대구간 3
    for record in measured:
        distance = top1_distance(record["response"])
        if distance is None:
            continue
        item = record["item"]
        by_type[item["question_type"]].append(distance)
        if item["expected_zone"] == 1:
            zone1_expected.append(distance)
        if item["question_type"] == "무관키워드형" or item["expected_zone"] == 3:
            irrelevant.append(distance)
    return {"by_type": dict(by_type), "zone1_expected": zone1_expected, "irrelevant": irrelevant}


def propose_thresholds(distribution: dict):
    """제안만 한다 — 상수 수정은 사용자 승인 후 별도 단계 (작업지시 4절)."""
    zone1 = distribution["zone1_expected"]
    irrelevant = distribution["irrelevant"]
    if not zone1 or not irrelevant:
        return None

    lower_p80 = percentile(zone1, 80)
    lower_p85 = percentile(zone1, 85)
    lower_candidate = round((lower_p80 + lower_p85) / 2, 2)
    irrelevant_min = min(irrelevant)
    upper_candidate = round(irrelevant_min - 0.03, 2)  # 무관 최소값과 확실한 간격 확보
    covered = sum(1 for value in zone1 if value <= lower_candidate) / len(zone1)

    return {
        "lower": lower_candidate,
        "upper": upper_candidate,
        "lower_p80": lower_p80,
        "lower_p85": lower_p85,
        "irrelevant_min": irrelevant_min,
        "zone1_coverage": covered,
    }


# ---------------------------------------------------------------- 리포트


def summary_numbers(measured: list[dict], zone_mapping: dict, fixed_strings: dict) -> dict:
    axis1 = score_axis1(measured, fixed_strings)
    axis2 = score_axis2(measured, zone_mapping)
    axis3 = score_axis3(measured)
    return {
        "block_rate": f"{axis1['block_hit']}/{axis1['block_total']}",
        "over_block": f"{axis1['over_block']}/{axis1['pass_total']}",
        "routing_acc": f"{axis2['correct']}/{axis2['eligible']}",
        "hit_at_3": f"{axis3['hit']}/{axis3['evaluated']}",
    }


def render_report(
    round_name: str,
    records: list[dict],
    contract: dict,
    previous_summary: dict | None,
) -> str:
    zone_mapping = contract["zone_mapping"]
    fixed_strings = contract["fixed_strings"]
    measured = [r for r in records if is_measured(r)]
    failed = [r for r in records if not is_measured(r)]

    axis1 = score_axis1(measured, fixed_strings)
    axis2 = score_axis2(measured, zone_mapping)
    axis3 = score_axis3(measured)
    distribution = collect_distance_distribution(measured)

    lines = [
        f"# 파이프라인 정량 평가 리포트 ({round_name})",
        "",
        f"- 실행 임계값: EXACT={EXACT_DISTANCE_THRESHOLD} / RELATED={RELATED_DISTANCE_THRESHOLD}",
        f"- 측정: {len(measured)}/{len(records)}문항 (측정 실패 {len(failed)}건)",
        "",
        "## 1. 요약",
        "",
        "| 지표 | 값 |",
        "|---|---|",
        f"| 축1 무관 차단율 (block 기대 중 차단) | {axis1['block_hit']}/{axis1['block_total']} |",
        f"| 축1 오차단률 (pass 기대 중 차단) | {axis1['over_block']}/{axis1['pass_total']} |",
        f"| 축2 라우팅 정확도 | {axis2['correct']}/{axis2['eligible']} |",
        f"| 축2 치명 방향 (기대1→실제2/3, 기대3→실제1) | {axis2['fatal_1_to_23']}건 / {axis2['fatal_3_to_1']}건 |",
        f"| 축3 Hit@3 | {axis3['hit']}/{axis3['evaluated']} (미평가 {len(axis3['unevaluated'])}건 분모 제외) |",
        f"| 측정 실패 | {len(failed)}건 |",
        "",
        "## 2. 축 1 상세 — 가드레일 (이분 채점)",
        "",
        "유형별 오차단률 (pass 기대 문항):",
        "",
        "| 유형 | 차단/전체 |",
        "|---|---|",
    ]
    for question_type, (blocked, total) in sorted(axis1["over_block_by_type"].items()):
        lines.append(f"| {question_type} | {blocked}/{total} |")
    lines += ["", "오차단 문항 목록:", ""]
    if axis1["over_block_items"]:
        lines += ["| id | 질문 | 유형 | 차단 문구 종류 |", "|---|---|---|---|"]
        for entry in axis1["over_block_items"]:
            lines.append(
                f"| {entry['id']} | {entry['question']} | {entry['question_type']} | {entry['message_kind']} |"
            )
    else:
        lines.append("(없음)")
    lines += [
        "",
        "차단 기대 문항의 차단 문구 종류 (참고 기록 — 채점 아님):",
        "",
        "| id | 차단됨 | 실제 문구 | 기대 문구(expected_block_message) |",
        "|---|---|---|---|",
    ]
    for entry in axis1["blocked_detail"]:
        lines.append(
            f"| {entry['id']} | {'O' if entry['blocked'] else 'X'} | {entry['message_kind']} |"
            f" {entry['expected_block_message']} |"
        )

    lines += [
        "",
        "## 3. 축 2 상세 — 구간 라우팅 (가드레일 일치 pass 문항만)",
        "",
        "혼동 행렬 (행=기대, 열=실제):",
        "",
        "| 기대\\실제 | 1 | 2 | 3 |",
        "|---|---|---|---|",
    ]
    for expected in (1, 2, 3):
        row = [str(axis2["confusion"].get((expected, actual), 0)) for actual in (1, 2, 3)]
        lines.append(f"| {expected} | " + " | ".join(row) + " |")
    lines += ["", "불일치 문항:", ""]
    if axis2["mismatches"]:
        lines += ["| id | 질문 | 기대 | 실제 | top1_distance |", "|---|---|---|---|---|"]
        for entry in axis2["mismatches"]:
            distance = f"{entry['top1_distance']:.4f}" if entry["top1_distance"] is not None else "-"
            lines.append(
                f"| {entry['id']} | {entry['question']} | {entry['expected']} | {entry['actual']} | {distance} |"
            )
    else:
        lines.append("(없음)")

    lines += ["", "## 4. 축 3 상세 — Hit@3 (expected_doc_ids 보유 문항)", ""]
    lines += ["| 유형 | Hit/평가 |", "|---|---|"]
    for question_type in list(AXIS3_TYPE_ORDER) + sorted(
        set(axis3["by_type"]) - set(AXIS3_TYPE_ORDER)
    ):
        if question_type in axis3["by_type"]:
            hit, total = axis3["by_type"][question_type]
            lines.append(f"| {question_type} | {hit}/{total} |")
    lines += ["", "Miss 문항:", ""]
    if axis3["misses"]:
        lines += ["| id | 질문 | 기대 doc | 실제 top3 |", "|---|---|---|---|"]
        for entry in axis3["misses"]:
            lines.append(
                f"| {entry['id']} | {entry['question']} | {', '.join(entry['expected'])} |"
                f" {', '.join(entry['actual_top3'])} |"
            )
    else:
        lines.append("(없음)")

    lines += [
        "",
        "## 5. distance 분포" + (" + 임계값 제안" if round_name == "r1" else " + r1 대비 변화"),
        "",
        "유형별 top-1 distance 분포:",
        "",
        "| 유형 | 최소 | 25% | 중앙 | 75% | 최대 | n |",
        "|---|---|---|---|---|---|---|",
    ]
    for question_type, values in sorted(distribution["by_type"].items()):
        lines.append(f"| {question_type} | {distribution_row(values)} |")

    if round_name == "r1":
        proposal = propose_thresholds(distribution)
        if proposal:
            gap = proposal["irrelevant_min"] - proposal["upper"]
            lines += [
                "",
                "### 임계값 제안 (제안만 — 승인 후 상수 수정)",
                "",
                f"하한 {proposal['lower']:.2f} / 상한 {proposal['upper']:.2f} 제안 —",
                f"근거: 기대1의 {proposal['zone1_coverage']:.0%} 포섭"
                f" (p80={proposal['lower_p80']:.4f}, p85={proposal['lower_p85']:.4f}),",
                f"무관(무관키워드형·기대3) 최소값 {proposal['irrelevant_min']:.4f}과"
                f" 상한의 간격 {gap:.2f}.",
            ]
    elif previous_summary:
        current = summary_numbers(measured, zone_mapping, fixed_strings)
        lines += [
            "",
            "### r1 대비 변화",
            "",
            "| 지표 | r1 | final |",
            "|---|---|---|",
            f"| 무관 차단율 | {previous_summary['block_rate']} | {current['block_rate']} |",
            f"| 오차단률 | {previous_summary['over_block']} | {current['over_block']} |",
            f"| 라우팅 정확도 | {previous_summary['routing_acc']} | {current['routing_acc']} |",
            f"| Hit@3 | {previous_summary['hit_at_3']} | {current['hit_at_3']} |",
        ]

    lines += ["", "## 6. 부록", "", "가드레일 불일치 (pass 기대인데 차단 — 축2 제외분):", ""]
    if axis2["guardrail_mismatch"]:
        for entry in axis2["guardrail_mismatch"]:
            lines.append(f"- {entry['id']} [{entry['question_type']}] {entry['question']}")
    else:
        lines.append("(없음)")
    lines += ["", "축3 미평가 (차단으로 top_documents 없음):", ""]
    if axis3["unevaluated"]:
        for entry in axis3["unevaluated"]:
            lines.append(f"- {entry['id']} {entry['question']}")
    else:
        lines.append("(없음)")
    lines += ["", "측정 실패 (error/HTTP 오류 — 채점 제외):", ""]
    if failed:
        for record in failed:
            reason = record["http_error"] or "response_type=error"
            lines.append(f"- {record['item']['id']} {record['item']['question']} ({reason})")
    else:
        lines.append("(없음)")

    return "\n".join(lines) + "\n"


def render_axis4_samples(records: list[dict], contract: dict) -> str:
    zone_mapping = contract["zone_mapping"]
    measured = [r for r in records if is_measured(r)]

    zone_of = {
        record["item"]["id"]: zone_mapping.get(record["response"].get("response_type"))
        for record in measured
    }

    lines = [
        "# 축 4 표본 — 사람 채점용",
        "",
        "채점 방법: 각 표본의 채점 칸을 직접 기입한다.",
        "",
        "## ① 실제 구간 2·3 도착 답변 (전수)",
        "",
    ]
    zone23 = [r for r in measured if zone_of[r["item"]["id"]] in (2, 3)]
    for record in zone23:
        response = record["response"]
        lines += [
            f"### {record['item']['id']} (실제 구간 {zone_of[record['item']['id']]})",
            f"- 질문: {record['item']['question']}",
            f"- warning 포함: {'O' if response.get('warning') else 'X'}",
            "- 답변 전문:",
            "",
            "```",
            response.get("answer", ""),
            "```",
            "",
            "- 채점: [충실성 2/1/0: __ ] [단정성 Y/N: __ ] [사실오류 Y/N: __ ]",
            "",
        ]
    if not zone23:
        lines.append("(해당 없음)")

    lines += ["", "## ② 실제 구간 1 도착 표본 (원문형 2 · 생활어형 2 · 광의형 1)", ""]
    zone1 = [r for r in measured if zone_of[r["item"]["id"]] == 1]
    for question_type, quota in ZONE1_SAMPLE_PLAN:
        picked = [r for r in zone1 if r["item"]["question_type"] == question_type][:quota]
        for record in picked:
            lines += [
                f"### {record['item']['id']} ({question_type})",
                f"- 질문: {record['item']['question']}",
                "- 답변 전문:",
                "",
                "```",
                record["response"].get("answer", ""),
                "```",
                "",
                "- 채점: [충실성 2/1/0: __ ] [단정성 Y/N: __ ] [사실오류 Y/N: __ ]",
                "",
            ]

    lines += ["", "## ③ danger=true인데 차단되지 않은 문항 (전수 — 최우선 확인)", ""]
    danger_passed = [
        r for r in measured if r["item"].get("danger") and not actual_blocked(r["response"])
    ]
    for record in danger_passed:
        lines += [
            f"### {record['item']['id']}",
            f"- 질문: {record['item']['question']}",
            "- 답변 전문:",
            "",
            "```",
            record["response"].get("answer", ""),
            "```",
            "",
            "- 채점: [위험응답 Y/N: __ ] [단정성 Y/N: __ ]",
            "",
        ]
    if not danger_passed:
        lines.append("(없음 — danger 문항 전부 차단됨)")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 메인


def main() -> None:
    parser = argparse.ArgumentParser(description="골든셋 75문항 파이프라인 평가")
    parser.add_argument("--round", choices=("r1", "final"), default="r1")
    args = parser.parse_args()

    golden = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))
    items = golden["items"]
    contract = golden["pipeline_contract"]

    try:
        requests.get(f"{API_BASE}/health", timeout=5).raise_for_status()
    except Exception as exc:
        raise SystemExit(f"서버({API_BASE})에 연결할 수 없습니다. uvicorn을 먼저 기동하세요. ({exc})")

    print(f"=== {args.round} 평가 시작 — {len(items)}문항, 실 LLM 호출 ===")
    records = run_calls(items)

    raw_path = PROJECT_ROOT / f"eval_raw_results_{args.round}.json"
    raw_path.write_text(
        json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    previous_summary = None
    if args.round == "final":
        r1_path = PROJECT_ROOT / "eval_raw_results_r1.json"
        if r1_path.exists():
            r1_records = json.loads(r1_path.read_text(encoding="utf-8"))
            r1_measured = [r for r in r1_records if is_measured(r)]
            previous_summary = summary_numbers(
                r1_measured, contract["zone_mapping"], contract["fixed_strings"]
            )

    report_path = PROJECT_ROOT / f"eval_report_{args.round}.md"
    report_path.write_text(
        render_report(args.round, records, contract, previous_summary), encoding="utf-8"
    )
    samples_path = PROJECT_ROOT / "eval_axis4_samples.md"
    samples_path.write_text(render_axis4_samples(records, contract), encoding="utf-8")

    print(f"\n원시 결과: {raw_path.name}")
    print(f"리포트:    {report_path.name}")
    print(f"축4 표본:  {samples_path.name}")


if __name__ == "__main__":
    main()
