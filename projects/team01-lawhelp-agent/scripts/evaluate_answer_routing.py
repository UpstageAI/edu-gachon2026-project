"""Day5 answer routing evaluation script.

This script evaluates the routing policy with real Chroma search results, but
does not call LLM generation. It parses DAY5_BRANCH_THRESHOLD_TEST_QUESTION_SET.md
and writes CSV/summary artifacts for threshold review.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Routing-only evaluation should not create Langfuse observations.
os.environ["LANGFUSE_ENABLED"] = "false"

from app.agents.domain_guardrail import classify_domain  # noqa: E402
from app.agents.nodes import AgentState, decide_route  # noqa: E402
from app.core.observability import DEFAULT_TOP_K  # noqa: E402
from app.core.routing import (  # noqa: E402
    EXACT_DISTANCE_THRESHOLD,
    RELATED_DISTANCE_THRESHOLD,
    AnswerRoute,
    DomainGuardrailResult,
)
from app.schemas.document import RetrievedDocument  # noqa: E402


QUESTION_SET_PATH = PROJECT_ROOT / "DAY5_BRANCH_THRESHOLD_TEST_QUESTION_SET.md"
DATASET_PATH = PROJECT_ROOT / "data" / "raw" / "baekmun_3categories.csv"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
CSV_OUTPUT_PATH = ARTIFACTS_DIR / "day5_routing_evaluation.csv"
SUMMARY_OUTPUT_PATH = ARTIFACTS_DIR / "day5_routing_evaluation_summary.md"

QUESTION_ID_PATTERN = re.compile(r"^(?:[GHL]-[RW]\d{2}|O-\d{2}|A-\d{2})$")
ROUTE_LABELS = {
    "OUT_OF_SCOPE": AnswerRoute.OUT_OF_SCOPE.value,
    "GROUNDED_RAG": AnswerRoute.GROUNDED_RAG.value,
    "RELATED_HYBRID": AnswerRoute.RELATED_HYBRID.value,
    "LLM_ONLY": AnswerRoute.LLM_ONLY.value,
    "ERROR": AnswerRoute.ERROR.value,
}
CORE_ROUTES = (
    AnswerRoute.OUT_OF_SCOPE.value,
    AnswerRoute.GROUNDED_RAG.value,
    AnswerRoute.RELATED_HYBRID.value,
    AnswerRoute.LLM_ONLY.value,
)


SearchFn = Callable[[str, int], list[RetrievedDocument]]


@dataclass(frozen=True)
class EvaluationQuestion:
    question_id: str
    question: str
    expected_route: str
    acceptable_routes: tuple[str, ...]
    expected_document_id: str = ""
    section: str = ""


@dataclass(frozen=True)
class EvaluationResult:
    question_id: str
    question: str
    expected_route: str
    acceptable_routes: str
    guardrail_result: str
    actual_route: str
    expected_document_id: str
    top1_document_id: str
    document_match: str
    top1_distance: str
    top2_distance: str
    top3_distance: str
    retrieved_count: int
    passed: str
    notes: str
    domain_category: str
    guardrail_reason: str
    suggested_topics: str

    def as_csv_row(self) -> dict[str, str | int]:
        return {
            "question_id": self.question_id,
            "question": self.question,
            "expected_route": self.expected_route,
            "acceptable_routes": self.acceptable_routes,
            "guardrail_result": self.guardrail_result,
            "actual_route": self.actual_route,
            "expected_document_id": self.expected_document_id,
            "top1_document_id": self.top1_document_id,
            "document_match": self.document_match,
            "top1_distance": self.top1_distance,
            "top2_distance": self.top2_distance,
            "top3_distance": self.top3_distance,
            "retrieved_count": self.retrieved_count,
            "pass": self.passed,
            "notes": self.notes,
            "domain_category": self.domain_category,
            "guardrail_reason": self.guardrail_reason,
            "suggested_topics": self.suggested_topics,
        }


def load_questions(path: Path = QUESTION_SET_PATH) -> list[EvaluationQuestion]:
    return load_questions_from_text(path.read_text(encoding="utf-8"))


def load_questions_from_text(text: str) -> list[EvaluationQuestion]:
    current_section = ""
    headers: list[str] = []
    questions: list[EvaluationQuestion] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            current_section = line
            headers = []
            continue
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cells = _parse_markdown_row(line)
        if not cells or _is_separator_row(cells):
            continue
        if "ID" in cells and "테스트 질문" in cells:
            headers = cells
            continue
        if not headers:
            continue

        row = _row_dict(headers, cells)
        question_id = _strip_formatting(row.get("ID", ""))
        if not QUESTION_ID_PATTERN.match(question_id):
            continue

        question = _strip_formatting(row.get("테스트 질문", ""))
        expected_cell = row.get("허용 결과") or row.get("기대 분기", "")
        acceptable_routes = _parse_acceptable_routes(expected_cell)
        if not question or not acceptable_routes:
            continue

        expected_route = acceptable_routes[0]
        expected_document_id = _strip_formatting(row.get("기준 백문 ID", ""))
        questions.append(
            EvaluationQuestion(
                question_id=question_id,
                question=question,
                expected_route=expected_route,
                acceptable_routes=acceptable_routes,
                expected_document_id=expected_document_id,
                section=current_section,
            )
        )

    return questions


def evaluate_questions(
    questions: list[EvaluationQuestion],
    *,
    search_fn: SearchFn | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> list[EvaluationResult]:
    search = search_fn or _default_search
    return [evaluate_question(question, search_fn=search, top_k=top_k) for question in questions]


def evaluate_question(
    question: EvaluationQuestion,
    *,
    search_fn: SearchFn,
    top_k: int = DEFAULT_TOP_K,
) -> EvaluationResult:
    decision = classify_domain(question.question)
    documents: list[RetrievedDocument] = []
    notes: list[str] = []

    if decision.result != DomainGuardrailResult.OUT_OF_SCOPE:
        try:
            documents = search_fn(question.question, top_k)
        except Exception as exc:
            return _error_result(question, decision, exc)

    state: AgentState = {
        "message": question.question,
        "documents": documents,
        "retrieved_count": len(documents),
        "domain_guardrail_result": decision.result.value,
        "domain_category": decision.domain_category,
        "guardrail_reason": decision.reason,
        "domain_keyword_hits": list(decision.domain_keyword_hits),
        "extended_domain_hits": list(decision.extended_domain_hits),
        "context_keyword_hits": list(decision.context_keyword_hits),
        "out_of_scope_hits": list(decision.out_of_scope_hits),
    }
    routed_state = decide_route(state)
    actual_route = str(routed_state.get("response_type", AnswerRoute.ERROR.value))
    route_passed = actual_route in question.acceptable_routes
    document_match = _document_matches(
        question.expected_document_id,
        str(routed_state.get("top1_document_id") or ""),
    )
    document_passed = True if not question.expected_document_id else document_match

    if not route_passed:
        notes.append(
            f"route mismatch: expected {question.acceptable_routes}, got {actual_route}"
        )
    if question.expected_document_id and not document_match:
        notes.append(
            "top1 document mismatch: "
            f"expected {question.expected_document_id}, "
            f"got {routed_state.get('top1_document_id') or ''}"
        )

    suggestions = [
        item.get("suggested_question", "")
        for item in routed_state.get("suggested_questions", [])
        if item.get("suggested_question")
    ]

    return EvaluationResult(
        question_id=question.question_id,
        question=question.question,
        expected_route=question.expected_route,
        acceptable_routes=";".join(question.acceptable_routes),
        guardrail_result=str(routed_state.get("domain_guardrail_result") or decision.result.value),
        actual_route=actual_route,
        expected_document_id=question.expected_document_id,
        top1_document_id=str(routed_state.get("top1_document_id") or ""),
        document_match=_format_bool(document_match) if question.expected_document_id else "",
        top1_distance=_format_distance(routed_state.get("top1_distance")),
        top2_distance=_format_distance(routed_state.get("top2_distance")),
        top3_distance=_format_distance(routed_state.get("top3_distance")),
        retrieved_count=int(routed_state.get("retrieved_count", 0)),
        passed=_format_bool(route_passed and document_passed),
        notes=" | ".join(notes),
        domain_category=str(routed_state.get("domain_category") or decision.domain_category),
        guardrail_reason=str(routed_state.get("guardrail_reason") or decision.reason),
        suggested_topics="; ".join(suggestions),
    )


def write_csv(results: list[EvaluationResult], path: Path = CSV_OUTPUT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(results[0].as_csv_row().keys()) if results else _csv_fieldnames()
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow(result.as_csv_row())


def write_summary(
    questions: list[EvaluationQuestion],
    results: list[EvaluationResult],
    path: Path = SUMMARY_OUTPUT_PATH,
    *,
    started_at: datetime | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        build_summary(questions, results, started_at=started_at, top_k=top_k),
        encoding="utf-8",
    )


def build_summary(
    questions: list[EvaluationQuestion],
    results: list[EvaluationResult],
    *,
    started_at: datetime | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> str:
    started_at = started_at or datetime.now().astimezone()
    total = len(results)
    passed = sum(1 for result in results if result.passed == "TRUE")
    failed = total - passed
    actual_counts = Counter(result.actual_route for result in results)
    expected_counts = Counter(question.expected_route for question in questions)
    core_results = [
        result for result in results if not result.question_id.startswith("A-")
    ]
    ambiguous_results = [
        result for result in results if result.question_id.startswith("A-")
    ]

    lines = [
        "# Day5 Routing Evaluation Summary",
        "",
        "## 실행 정보",
        "",
        f"- 실행 시각: {started_at.isoformat(timespec='seconds')}",
        f"- 질문셋: {QUESTION_SET_PATH.name}",
        f"- CSV 파일: {DATASET_PATH.name}",
        f"- CSV SHA256: {_file_sha256(DATASET_PATH)}",
        f"- Chroma collection: {_collection_info()}",
        "- embedding model: Upstage embedding-query",
        f"- exact_threshold: {EXACT_DISTANCE_THRESHOLD}",
        f"- related_threshold: {RELATED_DISTANCE_THRESHOLD}",
        f"- top_k: {top_k}",
        "- LLM generation: 호출하지 않음",
        "",
        "## 전체 결과",
        "",
        f"- 전체 질문 수: {total}",
        f"- PASS: {passed}",
        f"- FAIL: {failed}",
        "",
        "## 기대 분기 수",
        "",
        *_counter_lines(expected_counts),
        "",
        "## 실제 분기 수",
        "",
        *_counter_lines(actual_counts),
        "",
        "## Core Routing 혼동 행렬",
        "",
        _confusion_matrix(core_results),
        "",
        "## 모호성 질문 집계",
        "",
        f"- A-* 질문 수: {len(ambiguous_results)}",
        f"- A-* PASS: {sum(1 for result in ambiguous_results if result.passed == 'TRUE')}",
        "",
        "## Distance 분포",
        "",
        *_distance_distribution_lines(results),
        "",
        "## 오분기 질문",
        "",
        *_failed_result_lines(results),
        "",
        "## 임계값 의견",
        "",
        *_threshold_opinion_lines(results),
    ]
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Day5 answer routing without LLM calls.")
    parser.add_argument("--questions", type=Path, default=QUESTION_SET_PATH)
    parser.add_argument("--csv-output", type=Path, default=CSV_OUTPUT_PATH)
    parser.add_argument("--summary-output", type=Path, default=SUMMARY_OUTPUT_PATH)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    args = parser.parse_args()

    started_at = datetime.now().astimezone()
    questions = load_questions(args.questions)
    results = evaluate_questions(questions, top_k=args.top_k)
    write_csv(results, args.csv_output)
    write_summary(
        questions,
        results,
        args.summary_output,
        started_at=started_at,
        top_k=args.top_k,
    )
    print(f"questions={len(questions)}")
    print(f"csv={args.csv_output}")
    print(f"summary={args.summary_output}")
    return 0


def _default_search(query: str, top_k: int) -> list[RetrievedDocument]:
    from app.repositories.chroma_law_repository import search_law_qa_raw

    return search_law_qa_raw(query, top_k=top_k)


def _error_result(
    question: EvaluationQuestion,
    decision,
    exc: Exception,
) -> EvaluationResult:
    return EvaluationResult(
        question_id=question.question_id,
        question=question.question,
        expected_route=question.expected_route,
        acceptable_routes=";".join(question.acceptable_routes),
        guardrail_result=decision.result.value,
        actual_route=AnswerRoute.ERROR.value,
        expected_document_id=question.expected_document_id,
        top1_document_id="",
        document_match="FALSE" if question.expected_document_id else "",
        top1_distance="",
        top2_distance="",
        top3_distance="",
        retrieved_count=0,
        passed="FALSE",
        notes=f"search error: {type(exc).__name__}: {exc}",
        domain_category=decision.domain_category,
        guardrail_reason=decision.reason,
        suggested_topics="",
    )


def _parse_markdown_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip("|").split("|")]


def _is_separator_row(cells: list[str]) -> bool:
    return all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _row_dict(headers: list[str], cells: list[str]) -> dict[str, str]:
    return {header: cells[index] if index < len(cells) else "" for index, header in enumerate(headers)}


def _parse_acceptable_routes(text: str) -> tuple[str, ...]:
    normalized = _strip_formatting(text)
    routes = []
    for label, value in ROUTE_LABELS.items():
        if label in normalized and value not in routes:
            routes.append(value)
    return tuple(routes)


def _strip_formatting(text: str) -> str:
    return text.replace("`", "").strip()


def _document_matches(expected_document_id: str, actual_document_id: str) -> bool:
    expected = _strip_formatting(expected_document_id)
    actual = _strip_formatting(actual_document_id)
    if not expected:
        return False
    return actual == expected or actual == f"law_{expected}"


def _format_bool(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def _format_distance(value: object) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.6f}"
    except (TypeError, ValueError):
        return ""


def _csv_fieldnames() -> list[str]:
    return [
        "question_id",
        "question",
        "expected_route",
        "acceptable_routes",
        "guardrail_result",
        "actual_route",
        "expected_document_id",
        "top1_document_id",
        "document_match",
        "top1_distance",
        "top2_distance",
        "top3_distance",
        "retrieved_count",
        "pass",
        "notes",
        "domain_category",
        "guardrail_reason",
        "suggested_topics",
    ]


def _file_sha256(path: Path) -> str:
    if not path.exists():
        return "missing"
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _collection_info() -> str:
    try:
        from app.repositories.chroma_law_repository import COLLECTION_NAME, _get_collection

        collection = _get_collection()
        return f"{COLLECTION_NAME} ({collection.count()} documents)"
    except Exception as exc:
        return f"unavailable ({type(exc).__name__}: {exc})"


def _counter_lines(counter: Counter[str]) -> list[str]:
    if not counter:
        return ["- 없음"]
    return [f"- {key}: {counter[key]}" for key in sorted(counter)]


def _confusion_matrix(results: list[EvaluationResult]) -> str:
    matrix = {
        expected: {actual: 0 for actual in CORE_ROUTES}
        for expected in CORE_ROUTES
    }
    for result in results:
        expected = result.expected_route
        actual = result.actual_route
        if expected in matrix and actual in matrix[expected]:
            matrix[expected][actual] += 1

    header = "| 기대 \\ 실제 | " + " | ".join(CORE_ROUTES) + " |"
    separator = "|---|" + "|".join("---:" for _ in CORE_ROUTES) + "|"
    rows = [header, separator]
    for expected in CORE_ROUTES:
        values = " | ".join(str(matrix[expected][actual]) for actual in CORE_ROUTES)
        rows.append(f"| {expected} | {values} |")
    return "\n".join(rows)


def _distance_distribution_lines(results: list[EvaluationResult]) -> list[str]:
    lines = []
    for route in CORE_ROUTES:
        distances = [
            float(result.top1_distance)
            for result in results
            if result.expected_route == route and result.top1_distance
        ]
        if not distances:
            lines.append(f"- {route}: distance 없음")
            continue
        lines.append(
            f"- {route}: min={min(distances):.4f}, "
            f"max={max(distances):.4f}, avg={sum(distances) / len(distances):.4f}"
        )
    return lines


def _failed_result_lines(results: list[EvaluationResult]) -> list[str]:
    failed = [result for result in results if result.passed != "TRUE"]
    if not failed:
        return ["- 없음"]
    return [
        (
            f"- {result.question_id}: expected={result.acceptable_routes}, "
            f"actual={result.actual_route}, top1={result.top1_document_id}, "
            f"d={result.top1_distance or 'n/a'}, notes={result.notes or '-'}"
        )
        for result in failed
    ]


def _threshold_opinion_lines(results: list[EvaluationResult]) -> list[str]:
    grounded_to_related = _count_mismatch(
        results,
        expected=AnswerRoute.GROUNDED_RAG.value,
        actual=AnswerRoute.RELATED_HYBRID.value,
    )
    related_to_grounded = _count_mismatch(
        results,
        expected=AnswerRoute.RELATED_HYBRID.value,
        actual=AnswerRoute.GROUNDED_RAG.value,
    )
    llm_to_related = _count_mismatch(
        results,
        expected=AnswerRoute.LLM_ONLY.value,
        actual=AnswerRoute.RELATED_HYBRID.value,
    )
    out_to_in_scope = sum(
        1
        for result in results
        if result.expected_route == AnswerRoute.OUT_OF_SCOPE.value
        and result.actual_route != AnswerRoute.OUT_OF_SCOPE.value
    )

    lines = [
        f"- 현재 exact threshold: {EXACT_DISTANCE_THRESHOLD}",
        f"- 현재 related threshold: {RELATED_DISTANCE_THRESHOLD}",
        "- 이번 스크립트는 threshold 값을 변경하지 않음",
    ]
    if grounded_to_related:
        lines.append(
            f"- 직접 대응 질문 {grounded_to_related}건이 RELATED_HYBRID로 빠져 "
            "exact threshold 상향 후보를 검토할 수 있음"
        )
    if related_to_grounded:
        lines.append(
            f"- 연관 질문 {related_to_grounded}건이 GROUNDED_RAG로 들어가 "
            "exact threshold 하향 후보를 검토할 수 있음"
        )
    if llm_to_related:
        lines.append(
            f"- 데이터 공백 질문 {llm_to_related}건이 RELATED_HYBRID로 들어가 "
            "related threshold 하향 후보를 검토할 수 있음"
        )
    if out_to_in_scope:
        lines.append(
            f"- 범위 밖 질문 {out_to_in_scope}건이 범위 내 분기로 들어가 "
            "가드레일 규칙 보강을 검토할 수 있음"
        )
    if len(lines) == 3:
        lines.append("- 현재 결과만으로는 threshold 변경 후보를 제안하지 않음")
    return lines


def _count_mismatch(results: list[EvaluationResult], *, expected: str, actual: str) -> int:
    return sum(
        1
        for result in results
        if result.expected_route == expected and result.actual_route == actual
    )


if __name__ == "__main__":
    raise SystemExit(main())
