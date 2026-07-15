"""data.go.kr 참가격(ProductPriceInfoService) 실 API 클라이언트.

3개 오퍼레이션을 사용 (2026-07-14 실호출로 확인, 공식 문서에 파라미터가 나와 있지 않아
직접 프로빙해서 알아냄):
- getProductInfoSvc   : 품목 마스터 (604개 전체 — 식품 카테고리만 필터링해서 사용)
- getStoreInfoSvc     : 판매처(매장) 마스터 (약 615개)
- getProductPriceInfoSvc : 품목×매장 가격 관측치. goodInspectDay(YYYYMMDD) + goodId 또는
  entpId 중 하나가 반드시 필요 — 날짜만으로 전체 품목을 한 번에 못 가져옴(벌크 조회 불가).
  조사 주기는 KAMIS(매일)와 달리 전국 단위로 격주(2주 간격) 동일 조사일을 공유함
  (예: 2026-06-12, 2026-06-26엔 데이터 있고 그 사이 금요일엔 0건) — 그래서 아무 품목
  하나로 최신 조사일을 먼저 찾은 뒤(find_latest_inspect_day) 그 날짜를 전체 품목 조회에
  재사용하는 전략을 씀.

KAMIS와 달리 legacy SSL 이슈 없음 — 일반 requests로 handshake 정상 동작.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from typing import Any

import requests
from dotenv import load_dotenv
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

load_dotenv()

# [2026-07-15 추가] 457개 품목을 순회하며 매번 새 요청을 여는 fetch_prices_for_item에서
# 실제로 "Read timed out"(urllib3 ReadTimeoutError -> requests.ConnectionError)이 발생해
# 스크립트 전체가 중단된 것을 확인함(457개 중 50번째에서 실패, 이후 407개 미처리) —
# 공공 API가 가끔 응답을 늦게 주는 것으로 보여 재시도로 완화.
_RETRYABLE_ERRORS = (requests.exceptions.ConnectionError, requests.exceptions.Timeout)

_BASE_URL = "http://openapi.price.go.kr/openApiImpl/ProductPriceInfoService/"

# [2026-07-14 확인] goodSmlclsCode 앞 4자리 기준 대분류:
#   0301=신선식품(축산물·농산물·수산물), 0302=가공식품(라면·유제품·조미료·과자·음료·주류)
#   0303=비식품(화장품/위생용품·생활용품·반려동물용품) — 프로젝트 범위 밖이라 애초에 제외
_FOOD_CATEGORY_PREFIXES = ("0301", "0302")


def _service_key() -> str:
    """[2026-07-15 추가] 이전엔 os.environ["PRICE_GOKR_SERVICE_KEY"]를 그대로 써서, 이
    값이 빈 문자열일 때(예: GitHub Actions Secrets에 등록 자체가 안 된 경우 —
    ${{ secrets.X }}는 미등록이어도 예외 없이 빈 문자열로 치환됨) API가 "ServiceKey="로
    빈 채 호출돼 알아보기 힘든 404를 던졌음(실제 재현: price_gokr_daily_fetch cron 첫
    실행에서 발생). 원인을 바로 알 수 있도록 여기서 먼저 명확한 에러로 막는다.
    """
    key = os.environ.get("PRICE_GOKR_SERVICE_KEY", "")
    if not key:
        raise RuntimeError(
            "PRICE_GOKR_SERVICE_KEY가 비어있습니다. GitHub Actions Secrets에 "
            "'PRICE_GOKR_SERVICE_KEY' 이름으로 등록돼 있는지 확인하세요 "
            "(레포 Settings > Secrets and variables > Actions)."
        )
    return key


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=15),
    retry=retry_if_exception_type(_RETRYABLE_ERRORS),
)
def fetch_food_items() -> list[dict[str, Any]]:
    """전체 품목 카탈로그(604개) 중 식품 카테고리(0301/0302)만 필터링해서 반환."""
    res = requests.get(
        _BASE_URL + "getProductInfoSvc.do",
        params={"ServiceKey": _service_key()},
        timeout=15,
    )
    res.raise_for_status()
    root = ET.fromstring(res.content)

    items = []
    for item in root.findall(".//item"):
        smlcls = item.findtext("goodSmlclsCode", "") or ""
        if not smlcls.startswith(_FOOD_CATEGORY_PREFIXES):
            continue
        items.append(
            {
                "good_id": item.findtext("goodId"),
                "good_name": item.findtext("goodName"),
                "product_entp_code": item.findtext("productEntpCode"),
                "good_unit_div_code": item.findtext("goodUnitDivCode"),
                "good_base_cnt": item.findtext("goodBaseCnt"),
                "good_smlcls_code": smlcls,
                "good_total_cnt": item.findtext("goodTotalCnt"),
                "good_total_div_code": item.findtext("goodTotalDivCode"),
                "detail_mean": item.findtext("detailMean"),
            }
        )
    return items


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=15),
    retry=retry_if_exception_type(_RETRYABLE_ERRORS),
)
def fetch_all_stores() -> list[dict[str, Any]]:
    """전체 판매처(매장) 마스터 조회 (entpId 없이 호출하면 전체 목록 반환)."""
    res = requests.get(
        _BASE_URL + "getStoreInfoSvc.do",
        params={"ServiceKey": _service_key()},
        timeout=15,
    )
    res.raise_for_status()
    root = ET.fromstring(res.content)

    stores = []
    for row in root.findall(".//iros.openapi.service.vo.entpInfoVO"):
        stores.append(
            {
                "entp_id": row.findtext("entpId"),
                "entp_name": row.findtext("entpName"),
                "entp_type_code": row.findtext("entpTypeCode"),
                "entp_area_code": row.findtext("entpAreaCode"),
                "area_detail_code": row.findtext("areaDetailCode"),
                "entp_telno": row.findtext("entpTelno"),
                "post_no": row.findtext("postNo"),
                "plmk_addr_basic": row.findtext("plmkAddrBasic"),
                "plmk_addr_detail": row.findtext("plmkAddrDetail"),
                "road_addr_basic": row.findtext("roadAddrBasic"),
                "road_addr_detail": row.findtext("roadAddrDetail"),
                "x_map_coord": row.findtext("xMapCoord"),
                "y_map_coord": row.findtext("yMapCoord"),
            }
        )
    return stores


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=15),
    retry=retry_if_exception_type(_RETRYABLE_ERRORS),
)
def fetch_prices_for_item(good_id: str, inspect_day: str) -> list[dict[str, Any]]:
    """품목 하나(good_id)의 특정 조사일(YYYYMMDD) 매장별 가격 전체 조회.

    [2026-07-15 추가] 457개 품목을 순회하며 호출하는 도중 실제로 "Read timed out"이
    발생해 스크립트 전체가 중단된 것을 확인함 — 최대 3회까지 지수 백오프로 재시도.
    """
    res = requests.get(
        _BASE_URL + "getProductPriceInfoSvc.do",
        params={
            "ServiceKey": _service_key(),
            "goodInspectDay": inspect_day,
            "goodId": good_id,
        },
        timeout=15,
    )
    res.raise_for_status()
    root = ET.fromstring(res.content)

    rows = []
    for row in root.findall(".//iros.openapi.service.vo.goodPriceVO"):
        rows.append(
            {
                "good_inspect_day": row.findtext("goodInspectDay"),
                "entp_id": row.findtext("entpId"),
                "good_id": row.findtext("goodId"),
                "good_price": row.findtext("goodPrice"),
                "good_dc_yn": row.findtext("goodDcYn"),
                "input_dttm": row.findtext("inputDttm"),
            }
        )
    return rows


def find_latest_inspect_day(probe_good_id: str, max_lookback_days: int = 21) -> str | None:
    """조사 주기가 격주라 정확한 날짜를 미리 알 수 없어서, 오늘부터 하루씩
    거슬러가며 데이터가 있는 가장 최근 조사일을 품목 하나로 탐색.

    전체 품목이 같은 조사일을 공유한다는 것을 여러 품목으로 실측 확인했으므로
    (2026-07-14), 이렇게 찾은 날짜를 이후 전체 품목 조회에 그대로 재사용하면 됨.

    [2026-07-15 (4) 추가] fetch_prices_for_item 자체 재시도(3회)까지 다 소진해
    예외가 올라오는 경우(예: 특정 날짜 조회 중 커넥션 타임아웃 지속)를 실제로 겪음 —
    이전엔 이 루프에 try/except가 없어서 날짜 하나만 문제가 생겨도 최신 조사일 탐색
    전체가 죽어 [5/5] 가격 조회 단계 자체를 못 갔음. 그 날짜는 "데이터 없음"과 동일하게
    취급하고 하루 전으로 계속 탐색하도록 수정(scripts/fetch_price_gokr_snapshot.py의
    per-item skip-and-continue와 동일한 방어 패턴).
    """
    day = date.today()
    for _ in range(max_lookback_days):
        candidate = day.strftime("%Y%m%d")
        try:
            if fetch_prices_for_item(probe_good_id, candidate):
                return candidate
        except Exception as e:
            print(f"[find_latest_inspect_day] {candidate} 조회 실패, 건너뜀: {e!r}")
        day -= timedelta(days=1)
    return None
