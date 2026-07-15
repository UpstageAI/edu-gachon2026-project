"""Deterministic evidence gates for the three supported data sources.

These checks intentionally do not calculate a match score.  A source either
provides a usable candidate, a candidate is excluded by a hard condition, or
the condition remains unknown and is exposed as a warning for final review.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.core.dates import deadline_status
from app.core.regions import region_match_scope, resolve_region
from app.graph.search_contracts import SearchOutcome, SearchSource, SearchStatus
from app.repositories.youthcenter import is_narrow_youth_policy_query

_GENERIC_QUERY_WORDS = {
    "관련",
    "과정",
    "교육",
    "정보",
    "정책",
    "지원",
    "지원사업",
    "청년",
    "채용",
    "채용공고",
    "추천",
    "찾아줘",
    "알려줘",
}
_RELEVANCE_FAMILIES = (
    frozenset({"거주", "월세", "전세", "임대", "주거", "주거비"}),
    frozenset({"구직", "일경험", "일자리", "취업"}),
    frozenset({"강의", "교육", "역량", "자격증", "직업훈련", "훈련"}),
    frozenset({"금융", "복지", "생활", "자산", "자산형성"}),
    frozenset({"건강", "문화"}),
    frozenset({"권리", "기반", "참여", "청년활동", "커뮤니티"}),
)


def assess_search_outcome(
    outcome: SearchOutcome,
    *,
    profile: dict[str, Any],
    search_query: str | None,
) -> tuple[SearchOutcome, dict[str, Any]]:
    """Apply source-specific hard gates and return auditable rejection counts."""

    requested_region = profile.get("region")
    applied_filters = _gate_filters(
        outcome,
        profile=profile,
        requested_region=requested_region,
        search_query=search_query,
    )
    if not outcome.items:
        return outcome.model_copy(update={"applied_filters": applied_filters}), {
            "before_count": 0,
            "eligible_count": 0,
            "verified_count": 0,
            "unverified_count": 0,
            "after_count": 0,
            "rejection_reasons": {},
            "unverified_reasons": {},
        }

    accepted: list[dict[str, Any]] = []
    rejection_reasons: Counter[str] = Counter()
    unverified_reasons: Counter[str] = Counter()
    warnings = list(outcome.warnings)

    for raw_item in outcome.items:
        item = _annotate_match_scope(outcome.source, raw_item, requested_region)
        rejection = _candidate_rejection(
            outcome.source,
            item,
            profile=profile,
            requested_region=requested_region,
            search_query=search_query,
            career_level=outcome.applied_filters.get("career_level"),
        )
        if rejection:
            rejection_reasons[rejection] += 1
            continue
        candidate_unverified_reasons = _candidate_unverified_reasons(
            outcome.source,
            item,
            profile=profile,
            requested_region=requested_region,
            career_level=outcome.applied_filters.get("career_level"),
        )
        if candidate_unverified_reasons:
            unverified_reasons.update(candidate_unverified_reasons)
            item = {
                **item,
                "match_scope": "unknown",
                "evidence_status": "unverified",
                "unverified_reasons": candidate_unverified_reasons,
            }
        else:
            item = {
                **item,
                "evidence_status": "verified",
                "unverified_reasons": [],
            }
        accepted.append(item)

    if rejection_reasons:
        summary = ", ".join(f"{reason} {count}건" for reason, count in sorted(rejection_reasons.items()))
        warnings.append(f"결정적 근거 검증에서 후보를 제외했어요: {summary}")
    if unverified_reasons:
        summary = ", ".join(f"{reason} {count}건" for reason, count in sorted(unverified_reasons.items()))
        warnings.append(f"확인 근거가 부족한 후보를 원문 확인이 필요한 참고 결과로 유지했어요: {summary}")

    presented = _canonical_presented_candidates(accepted)
    status = outcome.status
    retryable = outcome.retryable
    if not presented and outcome.items and outcome.status is not SearchStatus.PARTIAL:
        status = SearchStatus.NO_MATCH
        retryable = False
    elif presented and outcome.status is SearchStatus.PARTIAL:
        status = SearchStatus.PARTIAL

    assessed = outcome.model_copy(
        update={
            "status": status,
            "items": presented,
            "applied_filters": applied_filters,
            "warnings": list(dict.fromkeys(warnings)),
            "retryable": retryable,
        }
    )
    return assessed, {
        "before_count": len(outcome.items),
        "eligible_count": len(accepted),
        "verified_count": sum(item.get("evidence_status") == "verified" for item in accepted),
        "unverified_count": sum(item.get("evidence_status") == "unverified" for item in accepted),
        "after_count": len(presented),
        "rejection_reasons": dict(rejection_reasons),
        "unverified_reasons": dict(unverified_reasons),
    }


def _gate_filters(
    outcome: SearchOutcome,
    *,
    profile: dict[str, Any],
    requested_region: str | None,
    search_query: str | None,
) -> dict[str, Any]:
    applied_filters = dict(outcome.applied_filters)
    if outcome.source is SearchSource.YOUTH_POLICY:
        if profile.get("age") is not None:
            applied_filters["age_gate"] = profile["age"]
        if requested_region:
            applied_filters["region_gate"] = requested_region
        if search_query and is_narrow_youth_policy_query(search_query):
            applied_filters["relevance_gate"] = search_query
    elif outcome.source is SearchSource.TRAINING and requested_region:
        applied_filters["region_post_filter"] = requested_region
    elif outcome.source is SearchSource.RECRUITMENT:
        applied_filters["allowed_item_types"] = ["event", "open_recruitment"]
        if requested_region:
            applied_filters["region_post_filter"] = requested_region
    return applied_filters


def _candidate_rejection(
    source: SearchSource,
    item: dict[str, Any],
    *,
    profile: dict[str, Any],
    requested_region: str | None,
    search_query: str | None,
    career_level: str | None,
) -> str | None:
    if _is_expired(source, item):
        return "closed"

    if source is SearchSource.YOUTH_POLICY:
        if age_rejection := _age_rejection(item, profile.get("age")):
            return age_rejection
        if item.get("match_scope") == "mismatch":
            return "region_mismatch"
        if search_query and is_narrow_youth_policy_query(search_query) and not _is_relevant(search_query, item):
            return "relevance_mismatch"
        return None

    if source is SearchSource.TRAINING:
        return _structured_region_mismatch(requested_region, item.get("region") or item.get("address"))

    if item.get("item_type") not in {"event", "open_recruitment"}:
        return "unsupported_recruitment_type"
    return _structured_region_mismatch(requested_region, item.get("region"))


def _candidate_unverified_reasons(
    source: SearchSource,
    item: dict[str, Any],
    *,
    profile: dict[str, Any],
    requested_region: str | None,
    career_level: str | None,
) -> list[str]:
    """Return missing-evidence reasons without turning them into exclusions."""

    reasons: list[str] = []
    if source is SearchSource.YOUTH_POLICY and _age_is_unverified(item, profile.get("age")):
        reasons.append("age_unverified")
    if requested_region and item.get("match_scope") == "unknown":
        reasons.append("region_unverified")
    if source is SearchSource.RECRUITMENT and career_level and item.get("item_type") == "event":
        career_evidence = " ".join(str(item.get(key) or "") for key in ("title", "summary"))
        if career_level not in career_evidence:
            reasons.append("career_unverified")
    return reasons


def _age_rejection(item: dict[str, Any], age: Any) -> str | None:
    if not isinstance(age, int) or isinstance(age, bool):
        return None
    minimum = item.get("min_age")
    maximum = item.get("max_age")
    if isinstance(minimum, int) and age < minimum:
        return "age_mismatch"
    if isinstance(maximum, int) and age > maximum:
        return "age_mismatch"
    return None


def _age_is_unverified(item: dict[str, Any], age: Any) -> bool:
    return (
        isinstance(age, int)
        and not isinstance(age, bool)
        and item.get("min_age") is None
        and item.get("max_age") is None
        and item.get("age_restricted") is not False
    )


def _is_expired(source: SearchSource, item: dict[str, Any]) -> bool:
    end_date = item.get("business_end_date") if source is SearchSource.YOUTH_POLICY else item.get("end_date")
    return isinstance(end_date, str) and deadline_status(end_date) == "마감"


def _structured_region_mismatch(requested_region: str | None, candidate_region: Any) -> str | None:
    if not requested_region:
        return None
    if not isinstance(candidate_region, str) or not candidate_region.strip():
        return None
    scope = _structured_region_scope(requested_region, candidate_region)
    if scope == "mismatch":
        return "region_mismatch"
    return None


def _annotate_match_scope(
    source: SearchSource,
    item: dict[str, Any],
    requested_region: str | None,
) -> dict[str, Any]:
    if source is SearchSource.YOUTH_POLICY:
        annotated = dict(item)
        candidate_region = item.get("region")
        if requested_region and isinstance(candidate_region, str) and candidate_region.strip():
            label_scope = region_match_scope(requested_region, [candidate_region])
            if label_scope == "mismatch":
                annotated["match_scope"] = "mismatch"
            elif annotated.get("match_scope") == "unknown" and label_scope in {"exact", "nationwide"}:
                annotated["match_scope"] = label_scope
        return annotated
    candidate_region = item.get("region") or (item.get("address") if source is SearchSource.TRAINING else None)
    if not requested_region or not isinstance(candidate_region, str) or not candidate_region.strip():
        scope = "unknown"
    else:
        resolved_scope = _structured_region_scope(requested_region, candidate_region)
        scope = resolved_scope if resolved_scope in {"exact", "nationwide"} else "unknown"
    return {**item, "match_scope": scope}


def _structured_region_scope(requested_region: str, candidate_region: str) -> str:
    """Compare both 시·도 and, when supplied on both sides, 시·군·구."""

    if "전국" in candidate_region:
        return "nationwide"
    broad_scope = region_match_scope(requested_region, [candidate_region])
    if broad_scope != "exact":
        return broad_scope

    requested = resolve_region(requested_region)
    candidate = resolve_region(candidate_region)
    if not requested or not candidate:
        return "unknown"
    if requested.sigungu and not candidate.sigungu:
        # A city/province-only record cannot prove a district-level request.
        # Keeping it would make a 서울 record look like an exact 강남구 match.
        return "unknown"
    if requested.sigungu and candidate.sigungu and requested.youth_code != candidate.youth_code:
        return "mismatch"
    return "exact"


def _canonical_presented_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select one stable, deduplicated candidate list for text/cards/snapshot."""

    seen_titles: set[str] = set()
    presented: list[dict[str, Any]] = []
    for item in items:
        title = " ".join(str(item.get("title") or "").lower().split())
        if title and title in seen_titles:
            continue
        if title:
            seen_titles.add(title)
        presented.append(item)
        if len(presented) == 3:
            break
    return presented


def _is_relevant(query: str, item: dict[str, Any]) -> bool:
    query_terms = _meaningful_terms(query)
    if not query_terms:
        return True
    evidence = " ".join(
        str(item.get(key) or "") for key in ("title", "target_summary", "support_summary", "organization")
    )
    evidence_terms = _meaningful_terms(evidence)
    if query_terms.intersection(evidence_terms):
        return True

    compact_query = re.sub(r"\s+", "", query)
    compact_evidence = re.sub(r"\s+", "", evidence)
    for family in _RELEVANCE_FAMILIES:
        if any(term in compact_query for term in family) and any(term in compact_evidence for term in family):
            return True
    return False


def _meaningful_terms(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[A-Za-z0-9+#가-힣]{2,}", value.lower()) if token not in _GENERIC_QUERY_WORDS
    }
