"""전자공시 조회 및 사업보고서 원문 수집(OpenDART)."""

from __future__ import annotations

import asyncio
import io
import re
import threading
import warnings
import zipfile
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from time import monotonic
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from loguru import logger

from app.core.config import settings

DART_API_BASE = "https://opendart.fss.or.kr/api"
DART_HTTP_TIMEOUT_SECONDS = 45.0


class DartAPIError(RuntimeError):
    """OpenDART가 오류 응답을 반환했을 때 발생합니다."""


@dataclass(frozen=True, slots=True)
class Corporation:
    corp_code: str
    corp_name: str
    stock_code: str | None = None


_corporation_cache: list[Corporation] | None = None
_corporation_cache_task: asyncio.Task[list[Corporation]] | None = None
_CORPORATION_CACHE_TASK_LOCK = threading.Lock()
_DISCLOSURE_CACHE_TTL_SECONDS = 300
_DISCLOSURE_CACHE_LOCK = threading.Lock()
_DISCLOSURE_CACHE: dict[tuple[str, int], tuple[float, list[dict]]] = {}

_KNOWN_CORPORATIONS = [
    Corporation("00126380", "삼성전자", "005930"),
    Corporation("00164779", "SK하이닉스", "000660"),
    Corporation("01515323", "LG에너지솔루션", "373220"),
    Corporation("00877059", "삼성바이오로직스", "207940"),
    Corporation("00164742", "현대자동차", "005380"),
    Corporation("00106641", "기아", "000270"),
    Corporation("00266961", "NAVER", "035420"),
    Corporation("00258801", "카카오", "035720"),
    Corporation("00155319", "POSCO홀딩스", "005490"),
    Corporation("00413046", "셀트리온", "068270"),
    Corporation("00356361", "LG화학", "051910"),
    Corporation("00126362", "삼성SDI", "006400"),
    Corporation("00126371", "삼성전기", "009150"),
    Corporation("00149655", "삼성물산", "028260"),
    Corporation("00401731", "LG전자", "066570"),
    Corporation("00164788", "현대모비스", "012330"),
    Corporation("00631518", "SK이노베이션", "096770"),
    Corporation("00159023", "SK텔레콤", "017670"),
    Corporation("00190321", "케이티", "030200"),
    Corporation("00231363", "LG유플러스", "032640"),
    Corporation("00159193", "한국전력공사", "015760"),
    Corporation("00126256", "삼성생명", "032830"),
    Corporation("00139214", "삼성화재해상보험", "000810"),
    Corporation("00688996", "KB금융", "105560"),
    Corporation("00382199", "신한지주", "055550"),
    Corporation("00547583", "하나금융지주", "086790"),
    Corporation("01350869", "우리금융지주", "316140"),
    Corporation("00860332", "메리츠금융지주", "138040"),
    Corporation("01133217", "카카오뱅크", "323410"),
    Corporation("00583424", "아모레퍼시픽", "090430"),
    Corporation("00360595", "현대글로비스", "086280"),
    Corporation("00111704", "한화오션", "042660"),
    Corporation("00126566", "한화에어로스페이스", "012450"),
    Corporation("00309503", "한국항공우주", "047810"),
    Corporation("00503668", "LIG디펜스앤에어로스페이스", "079550"),
    Corporation("00302926", "현대로템", "064350"),
    Corporation("00126478", "삼성중공업", "010140"),
    Corporation("01390344", "HD현대중공업", "329180"),
    Corporation("00159616", "두산에너빌리티", "034020"),
    Corporation("01105153", "두산로보틱스", "454910"),
    Corporation("00164645", "HMM", "011200"),
    Corporation("00113526", "대한항공", "003490"),
    Corporation("00536541", "에코프로", "086520"),
    Corporation("01160363", "에코프로비엠", "247540"),
    Corporation("00155276", "포스코퓨처엠", "003670"),
    Corporation("00124504", "포스코인터내셔널", "047050"),
    Corporation("00162461", "한화솔루션", "009830"),
    Corporation("00105873", "LG디스플레이", "034220"),
    Corporation("00760971", "크래프톤", "259960"),
    Corporation("00261443", "NC", "036570"),
    Corporation("00904672", "넷마블", "251270"),
    Corporation("01137383", "카카오게임즈", "293490"),
    Corporation("01204056", "하이브", "352820"),
    Corporation("01596425", "SK스퀘어", "402340"),
]

_KNOWN_CORPORATIONS_BY_STOCK = {
    corporation.stock_code: corporation
    for corporation in _KNOWN_CORPORATIONS
    if corporation.stock_code
}

_KNOWN_CORPORATION_ALIASES: dict[str, Corporation] = {
    "삼전": _KNOWN_CORPORATIONS_BY_STOCK["005930"],
    "하이닉스": _KNOWN_CORPORATIONS_BY_STOCK["000660"],
    "sk하이닉스": _KNOWN_CORPORATIONS_BY_STOCK["000660"],
    "현대차": _KNOWN_CORPORATIONS_BY_STOCK["005380"],
    "대우조선해양": _KNOWN_CORPORATIONS_BY_STOCK["042660"],
    "한화오션주": _KNOWN_CORPORATIONS_BY_STOCK["042660"],
    "셀트리온주": _KNOWN_CORPORATIONS_BY_STOCK["068270"],
    "네이버": _KNOWN_CORPORATIONS_BY_STOCK["035420"],
    "엔씨소프트": _KNOWN_CORPORATIONS_BY_STOCK["036570"],
}


class DartClient:
    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("DART_API_KEY가 필요합니다.")
        self.api_key = api_key
        self._client = client
        self._corporations: list[Corporation] | None = None

    async def _get(self, path: str, params: dict[str, str]) -> httpx.Response:
        request_params = {"crtfc_key": self.api_key, **params}
        if self._client:
            response = await self._client.get(path, params=request_params)
        else:
            async with httpx.AsyncClient(
                base_url=DART_API_BASE,
                timeout=DART_HTTP_TIMEOUT_SECONDS,
            ) as client:
                response = await client.get(path, params=request_params)
        response.raise_for_status()
        return response

    async def get_corporations(self) -> list[Corporation]:
        global _corporation_cache

        if self._corporations is None and _corporation_cache is not None:
            self._corporations = _corporation_cache
        if self._corporations is None:
            if self._client is not None:
                self._corporations = await self._download_corporations()
            else:
                self._corporations = await _get_shared_corporation_cache(self)
            _corporation_cache = self._corporations
        return self._corporations

    async def _download_corporations(self) -> list[Corporation]:
        response = await self._get("/corpCode.xml", {})
        corporations = parse_corporation_archive(response.content)
        logger.info(f"DART 기업 고유번호 목록 적재 완료: {len(corporations)}개")
        return corporations

    async def resolve_corporation(self, query: str) -> Corporation:
        known = _lookup_known_corporation(query)
        if known:
            return known

        normalized = _normalize_company_name(query)
        corporations = await self.get_corporations()

        exact = [
            corporation
            for corporation in corporations
            if query in {corporation.corp_code, corporation.stock_code}
            or _normalize_company_name(corporation.corp_name) == normalized
        ]
        if exact:
            return _prefer_listed_corporation(exact)

        partial = [
            corporation
            for corporation in corporations
            if normalized in _normalize_company_name(corporation.corp_name)
        ]
        if len(partial) == 1:
            return partial[0]
        if partial:
            listed = [item for item in partial if item.stock_code]
            if len(listed) == 1:
                return listed[0]
            candidates = ", ".join(
                f"{item.corp_name}({item.stock_code or item.corp_code})"
                for item in partial[:5]
            )
            raise DartAPIError(f"회사명이 모호합니다. 후보: {candidates}")
        raise DartAPIError(f"회사를 찾지 못했습니다: {query}")

    async def list_disclosures(
        self,
        corp_code: str,
        *,
        begin_date: str | None = None,
        end_date: str | None = None,
        report_type: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        today = date.today()
        end_date = end_date or today.strftime("%Y%m%d")
        begin_date = begin_date or (today - timedelta(days=365)).strftime("%Y%m%d")
        params = {
            "corp_code": corp_code,
            "bgn_de": begin_date,
            "end_de": end_date,
            "last_reprt_at": "Y",
            "sort": "date",
            "sort_mth": "desc",
            "page_no": "1",
            "page_count": str(min(max(limit, 1), 100)),
        }
        if report_type:
            params["pblntf_detail_ty"] = report_type

        response = await self._get("/list.json", params)
        payload = response.json()
        if payload.get("status") == "013":
            return []
        if payload.get("status") != "000":
            raise DartAPIError(
                f"공시검색 실패: {payload.get('status')} {payload.get('message')}"
            )
        return payload.get("list", [])[:limit]

    async def download_document(self, receipt_no: str) -> bytes:
        response = await self._get("/document.xml", {"rcept_no": receipt_no})
        if not response.content.startswith(b"PK"):
            message = response.content.decode("utf-8", errors="replace")[:300]
            raise DartAPIError(f"공시 원문 다운로드 실패: {message}")
        return response.content


async def get_recent_disclosures(corp: str, limit: int = 10) -> list[dict]:
    """회사명·종목코드·DART 고유번호로 최근 공시를 조회합니다."""
    if limit < 1:
        raise ValueError("limit must be greater than zero")

    cache_key = (_normalize_company_name(corp), limit)
    cached = _get_cached_disclosures(cache_key)
    if cached is not None:
        return cached

    client = DartClient(settings.dart_api_key)
    corporation = await client.resolve_corporation(corp)
    rows = await client.list_disclosures(corporation.corp_code, limit=limit)
    result = [
        {
            "receipt_no": row["rcept_no"],
            "corp_code": row["corp_code"],
            "corp_name": row["corp_name"],
            "stock_code": (row.get("stock_code") or "").strip() or None,
            "report_name": row["report_nm"],
            "received_date": row["rcept_dt"],
            "source_url": (
                f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={row['rcept_no']}"
            ),
        }
        for row in rows
    ]
    _set_cached_disclosures(cache_key, result)
    return result


async def _get_shared_corporation_cache(client: DartClient) -> list[Corporation]:
    """Share the expensive corpCode.xml download across concurrent requests.

    If a user request times out while the download is in progress, asyncio.shield keeps
    the shared task alive so the next request can reuse the completed cache instead of
    starting the same heavy OpenDART call again.
    """

    global _corporation_cache, _corporation_cache_task
    if _corporation_cache is not None:
        return _corporation_cache

    current_loop = asyncio.get_running_loop()
    with _CORPORATION_CACHE_TASK_LOCK:
        task = _corporation_cache_task
        needs_new_task = (
            task is None
            or task.cancelled()
            or task.get_loop() is not current_loop
            or (task.done() and task.exception() is not None)
        )
        if needs_new_task:
            task = asyncio.create_task(client._download_corporations())
            _corporation_cache_task = task

    try:
        corporations = await asyncio.shield(task)
    except Exception:
        with _CORPORATION_CACHE_TASK_LOCK:
            if _corporation_cache_task is task:
                _corporation_cache_task = None
        raise

    _corporation_cache = corporations
    return corporations


def start_corporation_cache_warmup() -> None:
    """Start a non-blocking OpenDART corporation-code warmup at API boot."""

    if not settings.dart_api_key or _corporation_cache is not None:
        return

    async def _warmup() -> None:
        try:
            client = DartClient(settings.dart_api_key)
            await client.get_corporations()
        except Exception as exc:
            logger.warning(
                f"DART 기업 고유번호 목록 사전 적재 실패: {type(exc).__name__}: {exc}"
            )

    try:
        asyncio.get_running_loop().create_task(_warmup())
        logger.info("DART 기업 고유번호 목록 사전 적재 시작")
    except RuntimeError:
        return


def _prefer_listed_corporation(corporations: list[Corporation]) -> Corporation:
    listed = [corporation for corporation in corporations if corporation.stock_code]
    if listed:
        return listed[0]
    return corporations[0]


def _get_cached_disclosures(cache_key: tuple[str, int]) -> list[dict] | None:
    now = monotonic()
    with _DISCLOSURE_CACHE_LOCK:
        cached = _DISCLOSURE_CACHE.get(cache_key)
        if cached is None:
            return None
        created_at, disclosures = cached
        if now - created_at > _DISCLOSURE_CACHE_TTL_SECONDS:
            _DISCLOSURE_CACHE.pop(cache_key, None)
            return None
        return deepcopy(disclosures)


def _set_cached_disclosures(
    cache_key: tuple[str, int],
    disclosures: list[dict],
) -> None:
    with _DISCLOSURE_CACHE_LOCK:
        _DISCLOSURE_CACHE[cache_key] = (monotonic(), deepcopy(disclosures))


async def get_business_report(corp: str) -> dict | None:
    """가장 최근 사업보고서(A001)의 원문을 내려받아 정제된 텍스트로 반환합니다."""
    metadata = await get_business_report_metadata(corp)
    if metadata is None:
        return None
    return await download_business_report(metadata)


async def get_business_report_metadata(corp: str) -> dict | None:
    """가장 최근 사업보고서의 메타데이터를 원문 다운로드 없이 반환합니다."""
    client = DartClient(settings.dart_api_key)
    corporation = await client.resolve_corporation(corp)
    rows = await client.list_disclosures(
        corporation.corp_code,
        begin_date=(date.today() - timedelta(days=1095)).strftime("%Y%m%d"),
        report_type="A001",
        limit=1,
    )
    if not rows:
        return None

    row = rows[0]
    return {
        "receipt_no": row["rcept_no"],
        "corp_code": row["corp_code"],
        "corp_name": row["corp_name"],
        "stock_code": (row.get("stock_code") or "").strip() or None,
        "report_name": row["report_nm"],
        "received_date": row["rcept_dt"],
        "source_url": (
            f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={row['rcept_no']}"
        ),
    }


async def download_business_report(metadata: dict) -> dict:
    """메타데이터에 해당하는 DART 원문을 내려받아 텍스트를 결합합니다."""
    client = DartClient(settings.dart_api_key)
    filename, content = extract_primary_document(
        await client.download_document(metadata["receipt_no"])
    )
    return {
        **metadata,
        "archive_filename": filename,
        "content": content,
    }


def parse_corporation_archive(content: bytes) -> list[Corporation]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            xml_name = next(
                name for name in archive.namelist() if name.lower().endswith(".xml")
            )
            root = ElementTree.fromstring(archive.read(xml_name))
    except (zipfile.BadZipFile, StopIteration, ElementTree.ParseError) as exc:
        raise DartAPIError("기업 고유번호 파일을 해석하지 못했습니다.") from exc

    return [
        Corporation(
            corp_code=(item.findtext("corp_code") or "").strip(),
            corp_name=(item.findtext("corp_name") or "").strip(),
            stock_code=(item.findtext("stock_code") or "").strip() or None,
        )
        for item in root.findall(".//list")
        if (item.findtext("corp_code") or "").strip()
        and (item.findtext("corp_name") or "").strip()
    ]


def extract_primary_document(archive_content: bytes) -> tuple[str, str]:
    try:
        with zipfile.ZipFile(io.BytesIO(archive_content)) as archive:
            candidates = [
                (info.filename, archive.read(info))
                for info in archive.infolist()
                if not info.is_dir()
                and Path(info.filename).suffix.lower()
                in {".xml", ".html", ".htm", ".txt"}
            ]
    except zipfile.BadZipFile as exc:
        raise DartAPIError("공시 원문이 ZIP 형식이 아닙니다.") from exc
    if not candidates:
        raise DartAPIError("공시 ZIP에서 텍스트 원문을 찾지 못했습니다.")

    filename, raw = max(candidates, key=lambda item: len(item[1]))
    decoded = _decode_text(raw)
    if Path(filename).suffix.lower() == ".txt":
        text = _normalize_text(decoded)
    else:
        # DART의 .xml은 실제 내용이 HTML/SGML에 가까워 html.parser가 더 관대하다.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
            soup = BeautifulSoup(decoded, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = _normalize_text(soup.get_text("\n"))
    if len(text) < 100:
        raise DartAPIError(f"추출된 공시 원문이 너무 짧습니다: {filename}")
    return filename, text


def _decode_text(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _normalize_text(text: str) -> str:
    lines: list[str] = []
    previous = ""
    for raw_line in text.replace("\u00a0", " ").replace("\u200b", "").splitlines():
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if not line or line == previous or re.fullmatch(r"-?\s*\d+\s*-?", line):
            continue
        lines.append(line)
        previous = line
    return "\n".join(lines)


def _normalize_company_name(value: str) -> str:
    return (
        value.lower()
        .replace("주식회사", "")
        .replace("(주)", "")
        .replace("㈜", "")
        .replace(" ", "")
        .strip()
    )


def _lookup_known_corporation(query: str) -> Corporation | None:
    normalized = _normalize_company_name(query)
    for corporation in _KNOWN_CORPORATIONS:
        if query in {corporation.corp_code, corporation.stock_code}:
            return corporation
        if normalized == _normalize_company_name(corporation.corp_name):
            return corporation

    return _KNOWN_CORPORATION_ALIASES.get(normalized)
