"""KAMIS dailyPriceByCategoryList 실 API 클라이언트.

- 부류코드(item_category_code) 단위로 요청 → 해당 부류의 전체 품목/품종/등급 row를 한 번에 받음
  (개별 품목 코드 매핑 불필요)
- KAMIS 서버가 legacy TLS 설정이라 기본 SSL 컨텍스트로는 handshake 실패 → 완화된 컨텍스트 사용
"""
from __future__ import annotations

import os
import ssl
from datetime import date
from typing import Any

import httpx
from dotenv import load_dotenv
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

load_dotenv()

_KAMIS_URL = "https://www.kamis.or.kr/service/price/xml.do"

# [2026-07-15 추가] GitHub Actions cron에서 "406 Not Acceptable"로 1회 실패한 것을 확인—
# 직전 실행 2회는 성공했고, 같은 요청을 이 환경에서 직접 재현해보면 200 OK가 나와서
# 특정 IP/시점에서만 걸리는 일시적 차단(WAF 등)으로 보임(cert_key/id 자체는 로그에서
# 마스킹(***)돼 있어 정상 등록된 상태였음 — 키 문제는 아님). httpx 기본 User-Agent만
# 쓰면 공공기관 WAF가 봇 요청으로 오인하기 쉬워 브라우저 형태 헤더를 명시하고,
# 그래도 실패하면 짧게 재시도하도록 방어.
_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}

# 부류코드 (KAMIS 실 응답으로 검증 완료)
CATEGORY_CODES: dict[str, str] = {
    "100": "식량작물",
    "200": "채소류",
    "300": "특용작물",
    "400": "과일류",
    "500": "축산물",
    "600": "수산물",
}


def _legacy_ssl_context() -> ssl.SSLContext:
    """KAMIS 서버의 오래된 TLS 설정과 handshake 하기 위한 완화된 컨텍스트."""
    ctx = ssl.create_default_context()
    ctx.options |= 0x4  # ssl.OP_LEGACY_SERVER_CONNECT
    ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    return ctx


def _require_env(name: str) -> str:
    """[2026-07-15 추가] price_gokr_client.py의 동일한 문제(GitHub Secrets 미등록 시
    빈 문자열이 그대로 API에 전달돼 알아보기 힘든 에러가 나는 것)를 여기서도 방지 —
    빈 값이면 원인을 바로 알 수 있는 에러로 막는다."""
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(
            f"{name}가 비어있습니다. GitHub Actions Secrets에 '{name}' 이름으로 "
            "등록돼 있는지 확인하세요 (레포 Settings > Secrets and variables > Actions)."
        )
    return value


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
)
def fetch_category_prices(
    category_code: str,
    regday: str | None = None,
    product_cls_code: str = "02",
) -> list[dict[str, Any]]:
    """부류코드 하나에 대한 전체 품목/품종/등급 가격 row를 반환.

    product_cls_code: "01"=도매, "02"=소매
    regday: "YYYY-MM-DD" (미지정 시 오늘)

    [2026-07-15 추가] "406 Not Acceptable" 1회 실패를 계기로 재시도(최대 3회, 지수
    백오프) 추가 — 같은 요청이 다른 시점/헤더로는 성공하는 걸 확인해서, 일시적
    차단으로 보고 방어적으로 재시도하도록 함.

    [2026-07-15 (2) 추가] 실제 cron 재발 로그(첫 카테고리 요청부터 406)를 보면 시도
    간격 2초/4초짜리 3회로는 부족할 수 있다고 판단 — 최대 시도 5회, 백오프 상한을
    30초로 늘려 차단이 좀 더 오래가는 경우까지 흡수하도록 함(최악의 경우 부류 하나당
    최대 약 2+4+8+16+30≈60초 대기, 6개 부류라 전체 cron이 과도하게 길어지진 않음).
    그래도 끝까지 실패하면 scripts/fetch_kamis_snapshot.py의 부류별 skip-and-continue가
    나머지 부류를 계속 처리하는 최종 방어선 역할을 함.
    """
    cert_key = _require_env("KAMIS_CERT_KEY")
    cert_id = _require_env("KAMIS_CERT_ID")

    params = {
        "action": "dailyPriceByCategoryList",
        "p_product_cls_code": product_cls_code,
        "p_item_category_code": category_code,
        "p_regday": regday or date.today().isoformat(),
        "p_convert_kg_yn": "N",
        "p_cert_key": cert_key,
        "p_cert_id": cert_id,
        "p_returntype": "json",
    }

    response = httpx.get(
        _KAMIS_URL, params=params, headers=_REQUEST_HEADERS, timeout=15, verify=_legacy_ssl_context()
    )
    response.raise_for_status()
    data = response.json()

    items = data.get("data", {}).get("item", [])
    if not isinstance(items, list):
        # KAMIS는 결과가 없거나 에러일 때 item을 dict/문자열로 반환하기도 함
        return []

    # KAMIS 응답 자체에는 부류코드가 없으므로(요청 파라미터로만 구분) 직접 주입
    for item in items:
        item["item_category_code"] = category_code
    return items


def fetch_all_categories(regday: str | None = None) -> list[dict[str, Any]]:
    """전체 부류(6종)를 순회하며 가격 row를 모두 수집."""
    all_items: list[dict[str, Any]] = []
    for category_code in CATEGORY_CODES:
        all_items.extend(fetch_category_prices(category_code, regday=regday))
    return all_items
