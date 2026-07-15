"""사용자 지역 표현과 온통청년 법정시군구코드를 정규화한다."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from typing import Literal

from app.core.administrative_regions import MUNICIPALITY_ROWS

RegionMatchScope = Literal["exact", "nationwide", "mismatch", "unknown"]

SIDO_CODE_PREFIXES = {
    "서울": "11",
    "전남광주": "12",
    "부산": "26",
    "대구": "27",
    "인천": "28",
    "광주": "29",
    "대전": "30",
    "울산": "31",
    "세종": "36",
    "경기": "41",
    "충북": "43",
    "충남": "44",
    "전남": "46",
    "경북": "47",
    "경남": "48",
    "제주": "50",
    "강원": "51",
    "전북": "52",
}

# 도로 이동 거리가 아니라 시·도 대표 좌표 간 직선거리다. 전국 시군구에
# 동일한 동작을 보장하고, 별도 좌표가 검증된 일부 지역만 더 세밀하게 쓴다.
SIDO_CENTERS = {
    "서울": (37.5665, 126.9780),
    "전남광주": (34.9878, 126.6574),
    "부산": (35.1796, 129.0756),
    "대구": (35.8714, 128.6014),
    "인천": (37.4563, 126.7052),
    "광주": (35.1595, 126.8526),
    "대전": (36.3504, 127.3845),
    "울산": (35.5384, 129.3114),
    "세종": (36.4800, 127.2890),
    "경기": (37.2749, 127.0095),
    "강원": (37.8854, 127.7298),
    "충북": (36.6357, 127.4915),
    "충남": (36.6588, 126.6728),
    "전북": (35.8203, 127.1088),
    "전남": (34.8161, 126.4629),
    "경북": (36.5760, 128.5056),
    "경남": (35.2383, 128.6924),
    "제주": (33.4996, 126.5312),
}

_SIDO_ALIASES = {
    "서울": "서울",
    "서울시": "서울",
    "서울특별시": "서울",
    "전남광주": "전남광주",
    "전남광주통합특별시": "전남광주",
    "부산": "부산",
    "부산시": "부산",
    "부산광역시": "부산",
    "대구": "대구",
    "대구시": "대구",
    "대구광역시": "대구",
    "인천": "인천",
    "인천시": "인천",
    "인천광역시": "인천",
    "광주": "광주",
    "광주광역시": "광주",
    "대전": "대전",
    "대전시": "대전",
    "대전광역시": "대전",
    "울산": "울산",
    "울산시": "울산",
    "울산광역시": "울산",
    "세종": "세종",
    "세종시": "세종",
    "세종특별자치시": "세종",
    "경기": "경기",
    "경기도": "경기",
    "강원": "강원",
    "강원도": "강원",
    "강원특별자치도": "강원",
    "충북": "충북",
    "충청북도": "충북",
    "충남": "충남",
    "충청남도": "충남",
    "전북": "전북",
    "전라북도": "전북",
    "전북특별자치도": "전북",
    "전남": "전남",
    "전라남도": "전남",
    "경북": "경북",
    "경상북도": "경북",
    "경남": "경남",
    "경상남도": "경남",
    "제주": "제주",
    "제주도": "제주",
    "제주특별자치도": "제주",
}

# 지방자치단체 기관명 판정에는 짧은 지명보다 공식 명칭만 사용한다.
_LOCAL_AUTHORITY_ALIASES = {
    alias: sido
    for alias, sido in _SIDO_ALIASES.items()
    if alias.endswith(("특별시", "광역시", "특별자치도", "경기도", "도")) and alias not in {"제주도", "강원도"}
}

_EQUIVALENT_SIDO_GROUP = frozenset({"전남광주", "광주", "전남"})
_SINGLE_MUNICIPALITY_SIDO_CODES = {"세종": "36110"}


@dataclass(frozen=True)
class RegionResolution:
    raw: str
    sido: str
    latitude: float
    longitude: float
    sigungu: str | None = None
    youth_code: str | None = None


@dataclass(frozen=True)
class _Municipality:
    sido: str
    name: str
    youth_code: str
    latitude: float
    longitude: float


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value).strip()


_PRECISE_MUNICIPALITY_CENTERS = {
    "41130": (37.4200, 127.1265),
    "41131": (37.4504, 127.1456),
    "41133": (37.4305, 127.1373),
    "41135": (37.3827, 127.1189),
    "28237": (37.5070, 126.7218),
    "44270": (36.8899, 126.6458),
}


def _municipality_from_row(sido: str, youth_code: str, name: str) -> _Municipality:
    latitude, longitude = _PRECISE_MUNICIPALITY_CENTERS.get(youth_code, SIDO_CENTERS[sido])
    return _Municipality(sido, name, youth_code, latitude, longitude)


_MUNICIPALITIES = tuple(_municipality_from_row(*row) for row in MUNICIPALITY_ROWS)
_MUNICIPALITY_BY_CODE = {item.youth_code: item for item in _MUNICIPALITIES}


def _municipality_aliases(item: _Municipality) -> tuple[set[str], set[str]]:
    full_name = _compact(item.name)
    leaf_name = _compact(item.name.split()[-1])
    exact_aliases = {full_name, leaf_name}
    if len(leaf_name) > 2 and leaf_name.endswith(("시", "군", "구")):
        exact_aliases.add(leaf_name[:-1])
    return exact_aliases, {full_name, leaf_name}


def _build_municipality_indexes() -> tuple[
    dict[str, tuple[_Municipality, ...]],
    dict[str, tuple[_Municipality, ...]],
]:
    exact: dict[str, list[_Municipality]] = defaultdict(list)
    contained: dict[str, list[_Municipality]] = defaultdict(list)
    for item in _MUNICIPALITIES:
        exact_aliases, contained_aliases = _municipality_aliases(item)
        for alias in exact_aliases:
            if item not in exact[alias]:
                exact[alias].append(item)
        for alias in contained_aliases:
            if item not in contained[alias]:
                contained[alias].append(item)
    return (
        {alias: tuple(items) for alias, items in exact.items()},
        {alias: tuple(items) for alias, items in contained.items()},
    )


_EXACT_MUNICIPALITY_INDEX, _CONTAINED_MUNICIPALITY_INDEX = _build_municipality_indexes()
_CONTAINED_ALIASES = tuple(sorted(_CONTAINED_MUNICIPALITY_INDEX, key=len, reverse=True))


def _build_suffixless_municipality_index() -> dict[str, tuple[_Municipality, ...]]:
    index: dict[str, list[_Municipality]] = defaultdict(list)
    for item in _MUNICIPALITIES:
        leaf_name = _compact(item.name.split()[-1])
        if len(leaf_name) <= 2 or not leaf_name.endswith(("시", "군", "구")):
            continue
        alias = leaf_name[:-1]
        if len(alias) >= 2 and item not in index[alias]:
            index[alias].append(item)
    return {alias: tuple(items) for alias, items in index.items()}


_SUFFIXLESS_MUNICIPALITY_INDEX = _build_suffixless_municipality_index()
_SUFFIXLESS_ALIASES = tuple(sorted(_SUFFIXLESS_MUNICIPALITY_INDEX, key=len, reverse=True))
_SUFFIXLESS_REGION_CONTEXT = re.compile(
    r"^[,.:;!?~]*(?:"
    r"(?:에|에서|으로|로)?(?:거주|사는|살고|살아|살아요|삽니다|살며)|"
    r"(?:이고|이며)?(?:만)?\d{1,3}(?:살|세)"
    r")"
)


def _formal_sido_hint(compact: str) -> str | None:
    matches = [(len(alias), sido) for alias, sido in _LOCAL_AUTHORITY_ALIASES.items() if alias in compact]
    return max(matches, default=(0, None))[1]


def _short_sido_hint(compact: str) -> str | None:
    matches = [(len(alias), sido) for alias, sido in _SIDO_ALIASES.items() if compact.startswith(alias)]
    return max(matches, default=(0, None))[1]


def _any_sido_hint(compact: str) -> str | None:
    matches = [(len(alias), sido) for alias, sido in _SIDO_ALIASES.items() if alias in compact]
    return max(matches, default=(0, None))[1]


def _select_municipality(
    candidates: tuple[_Municipality, ...] | list[_Municipality],
    sido_hint: str | None,
) -> _Municipality | None:
    filtered = [item for item in candidates if sido_hint is None or item.sido == sido_hint]
    if len(filtered) == 1:
        return filtered[0]
    if (
        filtered
        and {item.sido for item in filtered}.issubset(_EQUIVALENT_SIDO_GROUP)
        and len({item.name for item in filtered}) == 1
    ):
        return next(
            (item for item in filtered if item.sido == "전남광주"),
            filtered[0],
        )
    return None


def _best_contained_match(compact: str) -> tuple[str | None, tuple[_Municipality, ...]]:
    for alias in _CONTAINED_ALIASES:
        if alias in compact:
            return alias, _CONTAINED_MUNICIPALITY_INDEX[alias]
    return None, ()


def _best_contextual_suffixless_match(value: str) -> tuple[str | None, tuple[_Municipality, ...]]:
    """Find suffix-omitted municipalities only in explicit location-answer context.

    Treating every short name as an arbitrary substring turns ordinary Korean
    words such as "예산 지원" or "창의성 교육" into regions.  Exact short
    inputs remain supported by the exact index; sentence-level matching is
    limited to residence/location expressions and an adjacent age answer.
    """

    for alias in _SUFFIXLESS_ALIASES:
        for match in re.finditer(re.escape(alias), value):
            prefix = value[: match.start()]
            previous_character = value[match.start() - 1] if match.start() else ""
            has_left_boundary = not previous_character or not re.match(r"[0-9A-Za-z가-힣]", previous_character)
            compact_prefix = _compact(prefix)
            has_sido_prefix = compact_prefix in _SIDO_ALIASES or compact_prefix in _LOCAL_AUTHORITY_ALIASES
            if not has_left_boundary and not has_sido_prefix:
                continue
            suffix = _compact(value[match.end() :])
            if _SUFFIXLESS_REGION_CONTEXT.match(suffix):
                return alias, _SUFFIXLESS_MUNICIPALITY_INDEX[alias]
    return None, ()


def _municipality_resolution(raw: str, item: _Municipality) -> RegionResolution:
    return RegionResolution(
        raw,
        item.sido,
        item.latitude,
        item.longitude,
        sigungu=item.name,
        youth_code=item.youth_code,
    )


def _sido_resolution(raw: str, sido: str) -> RegionResolution:
    latitude, longitude = SIDO_CENTERS[sido]
    return RegionResolution(
        raw,
        sido,
        latitude,
        longitude,
        youth_code=_SINGLE_MUNICIPALITY_SIDO_CODES.get(sido),
    )


def resolve_region(value: str | None) -> RegionResolution | None:
    """전국 현존 시·군·구 이름을 표준 시·도와 5자리 코드로 변환한다.

    중구·고성군처럼 여러 시·도에 같은 이름이 있으면 시·도 없이 추정하지 않는다.
    """

    if not value:
        return None
    compact = _compact(value)
    if not compact:
        return None

    if compact in _SIDO_ALIASES:
        return _sido_resolution(value, _SIDO_ALIASES[compact])

    exact_candidates = _EXACT_MUNICIPALITY_INDEX.get(compact, ())
    exact_match = _select_municipality(exact_candidates, None)
    if exact_match:
        return _municipality_resolution(value, exact_match)

    formal_hint = _formal_sido_hint(compact)
    matched_alias, contained_candidates = _best_contained_match(compact)
    if contained_candidates:
        if formal_hint:
            formal_match = _select_municipality(contained_candidates, formal_hint)
            return _municipality_resolution(value, formal_match) if formal_match else None

        short_hint = _short_sido_hint(compact)
        if short_hint:
            hinted_match = _select_municipality(contained_candidates, short_hint)
            if hinted_match:
                return _municipality_resolution(value, hinted_match)

        unique_match = _select_municipality(contained_candidates, None)
        if unique_match:
            if (
                short_hint
                and short_hint != unique_match.sido
                and matched_alias
                and not compact.startswith(matched_alias)
            ):
                return None
            return _municipality_resolution(value, unique_match)
        return None

    contextual_alias, contextual_candidates = _best_contextual_suffixless_match(value)
    if contextual_candidates:
        contextual_hint = formal_hint or _any_sido_hint(compact)
        contextual_match = _select_municipality(contextual_candidates, contextual_hint)
        if contextual_match:
            return _municipality_resolution(value, contextual_match)
        return None

    sido_hint = formal_hint or _short_sido_hint(compact) or _any_sido_hint(compact)
    return _sido_resolution(value, sido_hint) if sido_hint else None


def user_region_reference(value: str | None) -> str | None:
    """사용자가 실제로 말한 지역을 추정 없이 표준 검색 문자열로 만든다."""

    # 지역을 정정하는 문장에서는 부정된 기존 지역보다 정정 대상이 우선한다.
    # 예: "경기도 말고 서울로"를 문장 전체 길이로만 비교하면 "경기도"가
    # 선택되므로, 전환 표현 뒤쪽을 먼저 해석한다.
    if value:
        correction_matches = list(re.finditer(r"말고|아니라|아니고|대신", value))
        if correction_matches:
            correction_target = value[correction_matches[-1].end() :]
            resolved_target = resolve_region(correction_target)
            if resolved_target:
                return (
                    f"{resolved_target.sido} {resolved_target.sigungu}"
                    if resolved_target.sigungu
                    else resolved_target.sido
                )

    resolved = resolve_region(value)
    if resolved:
        return f"{resolved.sido} {resolved.sigungu}" if resolved.sigungu else resolved.sido
    if not value:
        return None

    matched_alias, candidates = _best_contained_match(_compact(value))
    if candidates:
        return matched_alias
    contextual_alias, contextual_candidates = _best_contextual_suffixless_match(value)
    return contextual_alias if contextual_candidates else None


def _equivalent_sidos(sido: str) -> frozenset[str]:
    return _EQUIVALENT_SIDO_GROUP if sido in _EQUIVALENT_SIDO_GROUP else frozenset({sido})


def region_match_scope(
    user_region: str | None,
    policy_regions: list[str] | None,
) -> RegionMatchScope:
    if not user_region:
        return "unknown"
    regions = policy_regions or []
    if "전국" in regions:
        return "nationwide"
    user = resolve_region(user_region)
    if not user or not regions:
        return "unknown"

    policy_sidos = {resolved.sido for value in regions if (resolved := resolve_region(value)) is not None}
    if not policy_sidos:
        return "unknown"
    policy_equivalents = set().union(*(_equivalent_sidos(sido) for sido in policy_sidos))
    return "exact" if _equivalent_sidos(user.sido).intersection(policy_equivalents) else "mismatch"


def _haversine_km(origin: tuple[float, float], target: tuple[float, float]) -> float:
    lat1, lon1 = map(radians, origin)
    lat2, lon2 = map(radians, target)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    haversine = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 6371.0088 * 2 * asin(sqrt(haversine))


def region_distance_km(
    user_region: str | None,
    policy_regions: list[str] | None,
) -> float | None:
    origin = resolve_region(user_region)
    if not origin or not policy_regions or "전국" in policy_regions:
        return None

    distances: list[float] = []
    for value in policy_regions:
        target = resolve_region(value)
        if target:
            distances.append(
                _haversine_km(
                    (origin.latitude, origin.longitude),
                    (target.latitude, target.longitude),
                )
            )
    return round(min(distances), 1) if distances else None


def youth_codes(zip_codes: str | None) -> list[str]:
    return [code.strip() for code in (zip_codes or "").split(",") if code.strip()]


def youth_policy_is_nationwide(
    zip_codes: str | None,
    region_label: str | None = None,
) -> bool:
    if region_label == "전국":
        return True
    if region_label:
        return False
    prefixes = {
        sido
        for sido, prefix in SIDO_CODE_PREFIXES.items()
        if any(code.startswith(prefix) for code in youth_codes(zip_codes))
    }
    return len(prefixes) >= 15


def youth_policy_region_scope(
    user_region: str | None,
    zip_codes: str | None,
    region_label: str | None = None,
) -> RegionMatchScope:
    codes = youth_codes(zip_codes)
    raw_codes_are_nationwide = youth_policy_is_nationwide(zip_codes)

    if region_label == "전국":
        return "nationwide"
    if region_label and (raw_codes_are_nationwide or not codes):
        label_scope = region_match_scope(
            user_region,
            [part.strip() for part in region_label.split(",") if part.strip()],
        )
        if label_scope != "unknown":
            return label_scope
    if raw_codes_are_nationwide:
        return "nationwide"

    user = resolve_region(user_region)
    if not user:
        return "unknown"
    if not codes:
        return "unknown"

    # 시·도까지만 확인된 사용자를 특정 시·군·구 사업의 대상자로 간주하지 않는다.
    # 예: "경기" 사용자에게 평택시 전용 사업을 경기 전체 정책처럼 추천하지 않는다.
    if not user.sigungu and region_label:
        policy_region = resolve_region(region_label)
        if policy_region and policy_region.sigungu:
            return "unknown"

    if user.youth_code:
        code_prefix = user.youth_code[:4]
        return "exact" if any(code.startswith(code_prefix) for code in codes) else "mismatch"
    sido_prefix = SIDO_CODE_PREFIXES[user.sido]
    return "exact" if any(code.startswith(sido_prefix) for code in codes) else "mismatch"


def youth_region_label(zip_codes: str | None) -> str | None:
    codes = youth_codes(zip_codes)
    if not codes:
        return None
    if youth_policy_is_nationwide(zip_codes):
        return "전국"
    if len(codes) == 1 and (municipality := _MUNICIPALITY_BY_CODE.get(codes[0])):
        return municipality.name

    matched = [sido for sido, prefix in SIDO_CODE_PREFIXES.items() if any(code.startswith(prefix) for code in codes)]
    return ", ".join(matched) or zip_codes


def youth_local_authority_region_label(*organization_names: str | None) -> str | None:
    """등록·주관기관명에 명시된 지방자치단체의 시·도를 반환한다."""

    compact = _compact(" ".join(name for name in organization_names if name))
    if not compact:
        return None

    formal_hint = _formal_sido_hint(compact)
    if formal_hint:
        return formal_hint

    _, candidates = _best_contained_match(compact)
    municipality = _select_municipality(candidates, None)
    return municipality.sido if municipality else None
