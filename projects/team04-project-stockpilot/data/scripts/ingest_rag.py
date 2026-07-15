"""투자 용어·사업보고서 RAG 적재 스크립트.

기본 실행:
    uv run python data/scripts/ingest_rag.py

사업보고서 확인/적재:
    uv run python data/scripts/ingest_rag.py fetch-dart --company 삼성전자
    uv run python data/scripts/ingest_rag.py ingest-dart --company 삼성전자

Upstage Document AI 파일 적재:
    uv run python data/scripts/ingest_rag.py prepare-file \
      --path report.pdf --parser upstage --business-report --extract-facts
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.repositories.disclosure import get_business_report  # noqa: E402
from app.repositories.glossary import (  # noqa: E402
    ingest_glossary_terms,
    search_terms,
)
from app.repositories.rag import (  # noqa: E402
    chunk_document,
    ingest_business_report,
    ingest_glossary,
    select_business_report_chunks,
)
from app.services.document_ingestion import (  # noqa: E402
    ingest_document,
    prepare_document,
)
from app.services.report_cache import cache_business_reports  # noqa: E402

DEFAULT_GLOSSARY = PROJECT_ROOT / "data" / "glossary.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "rag"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="StockPilot RAG 적재 파이프라인")
    commands = parser.add_subparsers(dest="command")

    lookup_term = commands.add_parser(
        "lookup-term",
        help="search structured investment glossary terms",
    )
    lookup_term.add_argument("--query", required=True)
    lookup_term.add_argument("--limit", type=int, default=5)

    commands.add_parser("ingest-glossary", help="투자 용어 사전을 Supabase에 적재")

    fetch = commands.add_parser(
        "fetch-dart",
        help="최신 사업보고서를 받아 파싱·청킹 결과를 로컬에 저장",
    )
    fetch.add_argument("--company", required=True)
    fetch.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)

    ingest_dart = commands.add_parser(
        "ingest-dart",
        help="최신 사업보고서를 Supabase에 적재",
    )
    ingest_dart.add_argument("--company", required=True)

    batch = commands.add_parser(
        "ingest-dart-batch",
        help="주요 종목의 최신 사업보고서를 Supabase에 배치 적재",
    )
    batch.add_argument(
        "--companies",
        nargs="+",
        help="회사명 목록. 생략하면 기본 주요 종목 10개",
    )
    batch.add_argument(
        "--refresh",
        action="store_true",
        help="이미 캐시된 동일 접수번호도 다시 임베딩",
    )

    prepare_file = commands.add_parser(
        "prepare-file",
        help="PDF/TXT/Markdown을 파싱·청킹해 로컬에 저장",
    )
    prepare_file.add_argument("--path", type=Path, required=True)
    prepare_file.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    _add_document_ai_options(prepare_file)

    ingest_file = commands.add_parser(
        "ingest-file",
        help="PDF/TXT/Markdown을 Supabase에 적재",
    )
    ingest_file.add_argument("--path", type=Path, required=True)
    ingest_file.add_argument("--source-id")
    ingest_file.add_argument("--title")
    _add_document_ai_options(ingest_file)
    return parser.parse_args()


async def main_async(args: argparse.Namespace) -> None:
    command = args.command or "ingest-glossary"

    if command == "ingest-glossary":
        terms_saved = await ingest_glossary_terms(DEFAULT_GLOSSARY)
        saved = await ingest_glossary(DEFAULT_GLOSSARY)
        logger.success(f"structured glossary terms saved: {terms_saved}")
        logger.success(f"투자 용어 적재 완료: {saved} chunks")
        return

    if command == "lookup-term":
        matches = await search_terms(args.query, limit=args.limit)
        if not matches:
            logger.warning("no glossary term matched")
            return
        print(json.dumps(matches, ensure_ascii=False, indent=2))
        return

    if command in {"fetch-dart", "ingest-dart"}:
        report = await get_business_report(args.company)
        if report is None:
            logger.warning("조건에 맞는 사업보고서가 없습니다.")
            return

        metadata = {
            "source_type": "dart",
            "status": "active",
            "title": report["report_name"],
            "corp_code": report["corp_code"],
            "corp_name": report["corp_name"],
            "stock_code": report["stock_code"],
            "received_date": report["received_date"],
            "source_url": report["source_url"],
            "receipt_no": report["receipt_no"],
        }
        if command == "ingest-dart":
            saved = await ingest_business_report(
                source_id=f"dart:{report['receipt_no']}",
                content=report["content"],
                metadata=metadata,
            )
            logger.success(
                f"사업보고서 적재 완료: {report['report_name']} ({saved} chunks)"
            )
        else:
            chunks = chunk_document(report["content"])
            payload = {"document": metadata, "chunks": chunks}
            target = _save_json(
                payload,
                args.output_dir,
                f"{report['corp_name']}_{report['receipt_no']}.json",
            )
            logger.success(f"사업보고서 저장 완료: {target} ({len(chunks)} chunks)")
        return

    if command == "ingest-dart-batch":
        summary = await cache_business_reports(
            args.companies,
            refresh=args.refresh,
        )
        for item in summary.items:
            logger.info(
                f"[{item.status}] {item.company}: "
                f"chunks={item.chunks}, reason={item.reason}"
            )
        logger.success(
            "사업보고서 배치 캐시 완료: "
            f"total={summary.total}, cached={summary.cached}, "
            f"skipped={summary.skipped}, failed={summary.failed}"
        )
        return

    if command in {"prepare-file", "ingest-file"}:
        use_upstage = args.parser == "upstage"
        metadata = {
            "source_type": "local",
            "status": "active",
            "title": getattr(args, "title", None) or args.path.stem,
            "filename": args.path.name,
        }
        if command == "ingest-file":
            source_id = args.source_id or (f"local:{args.path.resolve().as_posix()}")
            result = await ingest_document(
                args.path,
                source_id=source_id,
                metadata=metadata,
                document_type=(
                    "business_report" if args.business_report else "general"
                ),
                use_upstage=use_upstage,
                fallback_to_local=not args.no_fallback,
                extract_facts=args.extract_facts,
            )
            logger.success(
                "로컬 문서 적재 완료: "
                f"{result.chunks_saved} chunks, parser={result.parser}, "
                f"facts_saved={result.facts_saved}"
            )
        else:
            prepared = await prepare_document(
                args.path,
                use_upstage=use_upstage,
                fallback_to_local=not args.no_fallback,
                extract_facts=args.extract_facts,
            )
            chunks = chunk_document(prepared.parsed.content)
            if args.business_report:
                chunks = select_business_report_chunks(chunks)
            target = _save_json(
                {
                    "document": {
                        **metadata,
                        "parser": prepared.parsed.parser,
                        "output_format": prepared.parsed.output_format,
                        "page_count": prepared.parsed.page_count,
                    },
                    "chunks": chunks,
                    "facts": (
                        prepared.facts.model_dump(mode="json")
                        if prepared.facts
                        else None
                    ),
                },
                args.output_dir,
                f"{args.path.stem}.json",
            )
            logger.success(f"로컬 문서 저장 완료: {target} ({len(chunks)} chunks)")


def _add_document_ai_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--parser",
        choices=("upstage", "local"),
        default="upstage",
        help="PDF·이미지는 Upstage Document Parse 사용(기본값)",
    )
    parser.add_argument(
        "--extract-facts",
        action="store_true",
        help="Upstage Information Extract로 사업보고서 핵심 필드 추출",
    )
    parser.add_argument(
        "--business-report",
        action="store_true",
        help="사업 내용·위험 섹션 중심으로 청크 선별",
    )
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="Document Parse 실패 시 로컬 pypdf fallback을 사용하지 않음",
    )


def _save_json(payload: dict, output_dir: Path, filename: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in filename
    )
    target = output_dir / safe_name
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


def main() -> None:
    asyncio.run(main_async(parse_args()))


if __name__ == "__main__":
    main()
