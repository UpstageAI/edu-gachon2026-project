"""온통청년 청년정책을 API로 가져와 Supabase youth_policies 테이블에 저장하는 배치 스크립트.

YouthCenterRepository.search()를 거치지 않고 API 호출 + 정규화 함수를 직접
사용한다 (search()는 특정 사용자 조건에 맞춘 지역 필터링/근접 정책 로직을 적용하는데,
캐시 인제스트는 조건 없이 최대한 넓게 수집하는 게 목적이라 그 로직이 필요 없다).

실행: uv run python data/scripts/ingest_youth_policies.py
필요 환경변수: YOUTHCENTER_POLICY_API_KEY, SUPABASE_URL, SUPABASE_KEY
"""

from __future__ import annotations

import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.core.config import Settings, get_settings  # noqa: E402
from app.repositories.youthcenter import (  # noqa: E402
    OFFICIAL_YOUTH_POLICY_API_URL,
    _latest_date_in_period,
    normalize_youth_policy_items,
    normalize_youth_policy_json,
)
from app.tools.schemas import YouthPolicyItem  # noqa: E402

PAGE_SIZE = 100
MAX_PAGES = 50  # 안전장치: 페이지네이션이 예상과 다르게 동작해도 무한 호출 방지

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,*/*",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


def _normalize_response(response: httpx.Response) -> list[YouthPolicyItem]:
    if "json" in response.headers.get("content-type", "").lower() or response.text.lstrip().startswith("{"):
        payload = response.json()
        if str(payload.get("resultCode")) != "200":
            print(f"[ingest_youth_policies] 비정상 응답 (result_code={payload.get('resultCode')}), 중단합니다.")
            return []
        return normalize_youth_policy_json(payload)
    return normalize_youth_policy_items(response.text)


def fetch_all_policies(settings: Settings) -> list[YouthPolicyItem]:
    api_url = settings.youthcenter_policy_api_url or OFFICIAL_YOUTH_POLICY_API_URL
    policies: list[YouthPolicyItem] = []

    with httpx.Client(timeout=15, headers=_HEADERS, follow_redirects=False) as client:
        for page in range(1, MAX_PAGES + 1):
            params = {
                "apiKeyNm": settings.youthcenter_policy_api_key,
                "pageNum": str(page),
                "pageSize": str(PAGE_SIZE),
            }
            try:
                response = client.get(api_url, params=params)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                print(f"[ingest_youth_policies] {page}페이지 요청 실패({exc}), 지금까지 모은 결과로 중단합니다.")
                break

            page_items = _normalize_response(response)
            if not page_items:
                break
            policies.extend(page_items)
            print(f"[ingest_youth_policies] {page}페이지: {len(page_items)}건")
            if len(page_items) < PAGE_SIZE:
                break

    return policies


def to_row(item: YouthPolicyItem, *, fetched_at: str) -> dict[str, Any]:
    row = item.model_dump(exclude={"fallback_reason", "raw", "match_scope", "distance_km"})
    row["raw_payload"] = item.raw
    row["fetched_at"] = fetched_at
    row["updated_at"] = fetched_at
    return row


def dedupe_by_key(rows: list[dict[str, Any]], *, key: Any) -> list[dict[str, Any]]:
    """같은 배치 안에 (source, policy_id)가 중복되면 Supabase upsert가
    'ON CONFLICT DO UPDATE command cannot affect row a second time' 류의
    409로 실패한다. 마지막 값을 남기고 먼저 나온 중복을 제거한다."""

    deduped: dict[Any, dict[str, Any]] = {}
    for row in rows:
        deduped[key(row)] = row
    return list(deduped.values())


def upsert_rows(settings: Settings, rows: list[dict[str, Any]]) -> None:
    headers = {
        "apikey": settings.supabase_key,
        "Authorization": f"Bearer {settings.supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    url = f"{settings.supabase_url}/rest/v1/youth_policies"

    with httpx.Client(timeout=30) as client:
        for i in range(0, len(rows), 200):
            batch = rows[i : i + 200]
            response = client.post(url, headers=headers, params={"on_conflict": "source,policy_id"}, json=batch)
            response.raise_for_status()
            print(f"[ingest_youth_policies] {len(batch)}건 upsert 완료 ({i + len(batch)}/{len(rows)})")


_YEAR_MONTH_PATTERN = re.compile(r"(?<!\d)(20\d{2})[.\-년]\s*(\d{1,2})월?(?!\d)")
_YEAR_ONLY_PATTERN = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def _latest_year_month_mentioned(value: str | None) -> tuple[int, int] | None:
    """'2025. 6. ~ 9.'처럼 일(day) 없이 연/월만 있어 _latest_date_in_period로는
    못 읽는 자유 텍스트(business_period)에서, 확인 가능한 가장 늦은 (연도, 월)을
    추정한다. "연도.월" 형태로 월이 명시된 곳은 그 달을 쓰고, 연도만 단독으로
    나오면(예: "2024~2027") 그 해 12월로 가정한다 — 일(day)까지는 표기 형식이
    너무 다양해 오판 위험이 있어서, 모르면 늦은 쪽으로 잡아 잘못 삭제할 위험을
    줄인다."""

    if not value:
        return None

    year_month_pairs = [
        (int(year_str), int(month_str))
        for year_str, month_str in _YEAR_MONTH_PATTERN.findall(value)
        if 1 <= int(month_str) <= 12
    ]
    if year_month_pairs:
        # 연/월이 명시된 값이 하나라도 있으면 그게 더 정확하니, 같은 텍스트 안의
        # 독립 연도(예: 위 연도가 다시 단독으로 매칭되는 경우)는 무시한다.
        return max(year_month_pairs)

    year_only_matches = [int(year_str) for year_str in _YEAR_ONLY_PATTERN.findall(value)]
    if year_only_matches:
        return (max(year_only_matches), 12)

    return None


def _is_expired(row: dict[str, Any], *, today: date) -> bool:
    """app.repositories.youthcenter._filter_active_youth_policies와 동일한 규칙:
    신청 마감일(application_period)을 우선 기준으로 삼고, 그걸로 판단할 수 없을 때
    사업 기간(business_end_date)으로 대체 판단한다. 그마저도 없으면, business_period
    자유 텍스트에서 추정한 (연도, 월)이 이번 달보다 확실히 이전인 경우에만 만료로
    처리한다."""

    application_end = _latest_date_in_period(row.get("application_period"))
    if application_end is not None:
        return application_end < today

    business_end = row.get("business_end_date")
    if business_end:
        try:
            return date.fromisoformat(business_end) < today
        except ValueError:
            pass

    latest_year_month = _latest_year_month_mentioned(row.get("business_period"))
    if latest_year_month is not None:
        return latest_year_month < (today.year, today.month)

    return False


def prune_expired_rows(settings: Settings) -> None:
    """신청 마감일(application_period) → 사업 종료일(business_end_date) → 사업기간
    자유 텍스트(business_period)에 언급된 연도 순으로 만료 여부를 판단해 삭제한다.
    셋 다 판단할 수 없는(NULL, 상시 모집 등) 행은 그대로 둔다."""

    headers = {
        "apikey": settings.supabase_key,
        "Authorization": f"Bearer {settings.supabase_key}",
    }
    today = datetime.now(UTC).date()

    rows: list[dict[str, Any]] = []
    offset = 0
    page = 1000
    with httpx.Client(timeout=30) as client:
        while True:
            response = client.get(
                f"{settings.supabase_url}/rest/v1/youth_policies",
                headers=headers,
                params={
                    "select": "id,application_period,business_end_date,business_period",
                    "order": "id.asc",
                    "offset": str(offset),
                    "limit": str(page),
                },
            )
            response.raise_for_status()
            batch = response.json()
            rows.extend(batch)
            if len(batch) < page:
                break
            offset += page

    expired_ids = [row["id"] for row in rows if _is_expired(row, today=today)]
    if not expired_ids:
        print("[ingest_youth_policies] 만료된 항목이 없습니다.")
        return

    delete_headers = {**headers, "Prefer": "return=representation"}
    deleted_total = 0
    with httpx.Client(timeout=30) as client:
        for i in range(0, len(expired_ids), 200):
            batch_ids = expired_ids[i : i + 200]
            response = client.delete(
                f"{settings.supabase_url}/rest/v1/youth_policies",
                headers=delete_headers,
                params={"id": f"in.({','.join(batch_ids)})"},
            )
            response.raise_for_status()
            deleted_total += len(response.json() if response.text else [])

    print(
        f"[ingest_youth_policies] 만료된 {deleted_total}건 삭제 완료 "
        "(신청 마감일 → 사업 종료일 → 사업기간 언급 연도 순으로 판단)"
    )


def main() -> None:
    settings = get_settings()

    missing = [
        name
        for name, value in (
            ("YOUTHCENTER_POLICY_API_KEY", settings.youthcenter_policy_api_key),
            ("SUPABASE_URL", settings.supabase_url),
            ("SUPABASE_KEY", settings.supabase_key),
        )
        if not value
    ]
    if missing:
        print(f"[ingest_youth_policies] 다음 환경변수가 없어 중단합니다: {', '.join(missing)}")
        return

    print("[ingest_youth_policies] 온통청년 청년정책 조회 중...")
    items = fetch_all_policies(settings)
    real_items = [item for item in items if not item.fallback_reason]
    print(f"[ingest_youth_policies] 총 {len(real_items)}건 조회 완료")

    if not real_items:
        print("[ingest_youth_policies] 저장할 데이터가 없어 종료합니다.")
        return

    fetched_at = datetime.now(UTC).isoformat()
    rows = [to_row(item, fetched_at=fetched_at) for item in real_items]
    rows = dedupe_by_key(rows, key=lambda row: (row["source"], row["policy_id"]))
    upsert_rows(settings, rows)
    print(f"[ingest_youth_policies] 완료: {len(rows)}건을 youth_policies 테이블에 저장했습니다.")

    prune_expired_rows(settings)


if __name__ == "__main__":
    main()
