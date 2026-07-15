"""고용24 채용행사/공채속보를 API로 가져와 Supabase
recruitment_infos 테이블에 저장하는 배치 스크립트.

Work24RecruitmentRepository.search()를 거치지 않고 API 호출 + 정규화 함수를 직접
사용한다 (search()는 사용자 조건에 맞춘 라운드로빈 병합 로직을 적용하는데, 캐시
인제스트는 조건 없이 3개 엔드포인트를 각각 최대한 넓게 수집하는 게 목적이다).

실행: uv run python data/scripts/ingest_recruitment_infos.py
필요 환경변수: EMPLOYMENT24_JOB_API_KEY, SUPABASE_URL, SUPABASE_KEY
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.core.config import Settings, get_settings  # noqa: E402
from app.repositories.work24_recruitment import normalize_recruitment_items  # noqa: E402
from app.tools.schemas import RecruitmentInfoItem  # noqa: E402

PAGE_SIZE = 100
MAX_PAGES = 100  # 안전장치: 페이지네이션이 예상과 다르게 동작해도 무한 호출 방지

_ENDPOINTS: tuple[tuple[str, str, str], ...] = (
    # (item_type, label, settings 필드명)
    ("open_recruitment", "공채속보", "employment24_open_recruitment_api_url"),
    ("event", "채용행사", "employment24_job_event_api_url"),
)


def fetch_all(settings: Settings, item_type: str, label: str, url: str) -> list[RecruitmentInfoItem]:
    items: list[RecruitmentInfoItem] = []

    with httpx.Client(timeout=20) as client:
        for page in range(1, MAX_PAGES + 1):
            params = {
                "authKey": settings.employment24_job_api_key,
                "callTp": "L",
                "returnType": "XML",
                "startPage": str(page),
                "display": str(PAGE_SIZE),
            }
            try:
                response = client.get(url, params=params)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                print(
                    f"[ingest_recruitment_infos] {label} {page}페이지 요청 실패({exc}), "
                    "지금까지 모은 결과로 중단합니다."
                )
                break

            try:
                page_items = normalize_recruitment_items(response.text, item_type)
            except ET.ParseError:
                print(f"[ingest_recruitment_infos] {label} {page}페이지 XML 파싱 실패, 중단합니다.")
                break

            if not page_items:
                break
            items.extend(page_items)
            print(f"[ingest_recruitment_infos] {label} {page}페이지: {len(page_items)}건")
            if len(page_items) < PAGE_SIZE:
                break

    return items


def to_row(item: RecruitmentInfoItem, *, fetched_at: str) -> dict[str, Any]:
    row = item.model_dump(exclude={"fallback_reason", "raw"})
    row["raw_payload"] = item.raw
    row["fetched_at"] = fetched_at
    row["updated_at"] = fetched_at
    return row


def dedupe_by_key(rows: list[dict[str, Any]], *, key: Any) -> list[dict[str, Any]]:
    """같은 배치 안에 (source, item_id)가 중복되면 Supabase upsert가
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
    url = f"{settings.supabase_url}/rest/v1/recruitment_infos"

    with httpx.Client(timeout=30) as client:
        for i in range(0, len(rows), 200):
            batch = rows[i : i + 200]
            response = client.post(url, headers=headers, params={"on_conflict": "source,item_id"}, json=batch)
            response.raise_for_status()
            print(f"[ingest_recruitment_infos] {len(batch)}건 upsert 완료 ({i + len(batch)}/{len(rows)})")


def prune_expired_rows(settings: Settings) -> None:
    """end_date가 오늘보다 지난 채용정보를 삭제한다.

    종료일이 없는 행은 만료 여부를 판단할 수 없으므로 그대로 둔다.
    """

    today = datetime.now(UTC).date().isoformat()
    headers = {
        "apikey": settings.supabase_key,
        "Authorization": f"Bearer {settings.supabase_key}",
        "Prefer": "return=representation",
    }
    with httpx.Client(timeout=30) as client:
        response = client.delete(
            f"{settings.supabase_url}/rest/v1/recruitment_infos",
            headers=headers,
            params={"end_date": f"lt.{today}"},
        )
        response.raise_for_status()
        deleted = response.json() if response.text else []
        print(f"[ingest_recruitment_infos] 만료된 {len(deleted)}건 삭제 완료 (end_date < {today})")


def main() -> None:
    settings = get_settings()

    missing = [
        name
        for name, value in (
            ("EMPLOYMENT24_JOB_API_KEY", settings.employment24_job_api_key),
            ("SUPABASE_URL", settings.supabase_url),
            ("SUPABASE_KEY", settings.supabase_key),
        )
        if not value
    ]
    if missing:
        print(f"[ingest_recruitment_infos] 다음 환경변수가 없어 중단합니다: {', '.join(missing)}")
        return

    all_items: list[RecruitmentInfoItem] = []
    for item_type, label, url_field in _ENDPOINTS:
        url = getattr(settings, url_field)
        print(f"[ingest_recruitment_infos] 고용24 {label} 조회 중...")
        all_items.extend(fetch_all(settings, item_type, label, url))

    real_items = [item for item in all_items if not item.fallback_reason]
    print(f"[ingest_recruitment_infos] 총 {len(real_items)}건 조회 완료")

    if not real_items:
        print("[ingest_recruitment_infos] 저장할 데이터가 없어 종료합니다.")
        return

    fetched_at = datetime.now(UTC).isoformat()
    rows = [to_row(item, fetched_at=fetched_at) for item in real_items]
    rows = dedupe_by_key(rows, key=lambda row: (row["source"], row["item_id"]))
    upsert_rows(settings, rows)
    print(f"[ingest_recruitment_infos] 완료: {len(rows)}건을 recruitment_infos 테이블에 저장했습니다.")

    prune_expired_rows(settings)


if __name__ == "__main__":
    main()
