from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SearchStatus(StrEnum):
    """A source search result status that does not conflate failure with no match."""

    SUCCESS = "success"
    NO_MATCH = "no_match"
    UNAVAILABLE = "unavailable"
    PARTIAL = "partial"


class SearchSource(StrEnum):
    """Search sources supported by the policy agent graph."""

    YOUTH_POLICY = "youth_policy"
    TRAINING = "training"
    RECRUITMENT = "recruitment"


class SearchOutcome(BaseModel):
    """Normalized boundary between source tools and the orchestration graph.

    Guide/fallback records are deliberately represented as warnings rather than
    candidate items. This prevents an API failure guide from being recommended
    as if it were an actual policy, course, or recruitment result.
    """

    source: SearchSource
    status: SearchStatus
    items: list[dict[str, Any]] = Field(default_factory=list)
    requested_filters: dict[str, Any] = Field(default_factory=dict)
    applied_filters: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    retryable: bool = False


_NO_MATCH_MARKERS = (
    "검색 결과 없음",
    "결과 없음",
    "검색 결과를 찾지 못",
    "바로 찾지 못",
    "허용된 고용24 채용 API 결과 없음",
)
_UNAVAILABLE_MARKERS = (
    "미설정",
    "설정되지",
    "호출 실패",
    "파싱 실패",
    "응답하지",
    "조회할 수 없",
    "권한 제한",
    "사용할 수 없는",
    "일시적으로",
)
_NON_RETRYABLE_MARKERS = (
    "미설정",
    "설정되지",
    "권한 제한",
    "사용할 수 없는",
)
_GUIDE_IDS = {
    "youthcenter-guide",
    "work24-training-guide",
    "work24-recruitment-guide",
}


def outcome_from_raw(
    source: SearchSource | str,
    values: Sequence[BaseModel | Mapping[str, Any]] | None,
    *,
    requested_filters: Mapping[str, Any] | None = None,
    applied_filters: Mapping[str, Any] | None = None,
    warnings: Sequence[str] | None = None,
) -> SearchOutcome:
    """Convert a legacy list result into a status-aware ``SearchOutcome``.

    This public adapter also keeps graph tests and locally defined fake tools
    compatible while each integration migrates from ``execute`` to
    ``execute_outcome``.
    """

    normalized_items: list[dict[str, Any]] = []
    normalized_warnings = [str(warning).strip() for warning in warnings or [] if str(warning).strip()]
    guide_statuses: list[SearchStatus] = []

    for value in values or []:
        item = _item_as_dict(value)
        if not _is_guide_item(item):
            # Upstream raw payloads can be large and may contain fields that
            # are not approved for prompts, traces, cards, or session state.
            item.pop("raw", None)
            item.pop("raw_payload", None)
            normalized_items.append(item)
            continue

        warning = _guide_warning(item)
        if warning:
            normalized_warnings.append(warning)
        guide_statuses.append(_classify_guide_status(warning))

    normalized_warnings = _deduplicate(normalized_warnings)
    status, retryable = _resolve_status(
        has_items=bool(normalized_items),
        guide_statuses=guide_statuses,
        warnings=normalized_warnings,
    )
    return SearchOutcome(
        source=source,
        status=status,
        items=normalized_items,
        requested_filters=dict(requested_filters or {}),
        applied_filters=dict(applied_filters or {}),
        warnings=normalized_warnings,
        retryable=retryable,
    )


def unavailable_outcome(
    source: SearchSource | str,
    warning: str,
    *,
    requested_filters: Mapping[str, Any] | None = None,
    applied_filters: Mapping[str, Any] | None = None,
) -> SearchOutcome:
    """Build an explicit tool/integration failure result."""

    return SearchOutcome(
        source=source,
        status=SearchStatus.UNAVAILABLE,
        requested_filters=dict(requested_filters or {}),
        applied_filters=dict(applied_filters or {}),
        warnings=[warning],
        retryable=True,
    )


def _item_as_dict(value: BaseModel | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return dict(value)
    if callable(model_dump := getattr(value, "model_dump", None)):
        return dict(model_dump())
    raise TypeError(f"Search result items must be Pydantic models or mappings, got {type(value)!r}")


def _is_guide_item(item: Mapping[str, Any]) -> bool:
    identifiers = {
        item.get("policy_id"),
        item.get("course_id"),
        item.get("item_id"),
    }
    return bool(item.get("fallback_reason") or item.get("item_type") == "guide" or identifiers.intersection(_GUIDE_IDS))


def _guide_warning(item: Mapping[str, Any]) -> str:
    for key in ("fallback_reason", "summary", "title"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "검색 소스가 실제 후보 대신 안내 레코드를 반환했습니다."


def _classify_guide_status(warning: str) -> SearchStatus:
    if any(marker in warning for marker in _NO_MATCH_MARKERS):
        return SearchStatus.NO_MATCH
    if any(marker in warning for marker in _UNAVAILABLE_MARKERS):
        return SearchStatus.UNAVAILABLE
    # An unrecognized guide is not evidence that there were no matching records.
    return SearchStatus.UNAVAILABLE


def _resolve_status(
    *,
    has_items: bool,
    guide_statuses: Sequence[SearchStatus],
    warnings: Sequence[str],
) -> tuple[SearchStatus, bool]:
    if has_items:
        if guide_statuses or warnings:
            return SearchStatus.PARTIAL, SearchStatus.UNAVAILABLE in guide_statuses
        return SearchStatus.SUCCESS, False

    if SearchStatus.UNAVAILABLE in guide_statuses:
        retryable = not any(marker in warning for warning in warnings for marker in _NON_RETRYABLE_MARKERS)
        return SearchStatus.UNAVAILABLE, retryable
    if guide_statuses and all(status is SearchStatus.NO_MATCH for status in guide_statuses):
        return SearchStatus.NO_MATCH, False
    if warnings:
        # Caller-provided warnings without candidates are conservatively treated
        # as unavailable, never as proof that the search had zero matches.
        return SearchStatus.UNAVAILABLE, True
    return SearchStatus.NO_MATCH, False


def _deduplicate(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))
