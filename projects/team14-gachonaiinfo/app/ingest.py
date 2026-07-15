"""
데이터 적재: 정형 카탈로그 + 졸업요건 + RAG 청크 → PostgreSQL/pgvector

사용법:
    python -m app.ingest
"""

import json
import re

from app import config, db, embeddings, retrieval
from app.core.graduation import load_graduation_records

CHUNK_TARGET = 700  # 청크 목표 길이(문자)

# 권위 있는 '기준/요건' 문서만 priority 1(핵심), 나머지(절차·목록·일정)는 2.
# priority 는 소수의 핵심 문서를 구분하기 위한 것이라 넓게 주지 않는다. (멘토링 결과 §8)
_PRIORITY_BY_L2 = {
    "foreign_language": 1,
    "credit_requirement": 1,
    "requirement": 1,
}


def doc_meta(source: str, content: str, cat_l2: str | None, cat_l1: str | None = None) -> dict:
    """reranker 용 메타 계산: priority, academic_year, semester, keywords."""
    priority = _PRIORITY_BY_L2.get(cat_l2 or "", 2)
    # 학년도는 '제목'에서만 추출한다. 본문 연도(예: 2015학번, 2022.06.04)는
    # 문서의 학년도가 아니라 오탐이므로 쓰지 않는다.
    ym = re.search(r"20\d{2}", source)
    academic_year = int(ym.group()) if ym else None
    sm = re.search(r"([1-2])\s*학기", source)
    semester = f"{sm.group(1)}학기" if sm else None
    # 키워드: 제목 토큰 + 카테고리명 (질문-문서 매칭 보조)
    kws = retrieval.tokenize(source) + [c for c in (cat_l1, cat_l2) if c]
    keywords = list(dict.fromkeys(kws))  # 중복 제거, 순서 유지
    return {
        "priority": priority,
        "academic_year": academic_year,
        "semester": semester,
        "keywords": keywords,
    }


CHUNK_MIN = 200  # 이보다 짧으면 다음 블록과 합침

MANIFEST = config.PARSED_DIR / "_crawl_manifest.json"
_CATEGORY_HEADER = re.compile(r"^>\s*카테고리:\s*([A-Za-z_]+)\s*/\s*([A-Za-z_]+)", re.M)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_category_map() -> dict[str, tuple[str, str]]:
    """_crawl_manifest.json → {source: (category_l1, category_l2)}."""
    if not MANIFEST.exists():
        return {}
    out = {}
    for m in load_json(MANIFEST):
        if m.get("category_l1"):
            out[m["source"]] = (m["category_l1"], m.get("category_l2"))
    return out


def category_for(source: str, md: str, cat_map: dict) -> tuple[str | None, str | None]:
    """카테고리 결정: manifest 우선, 없으면 .md 헤더의 `> 카테고리: l1/l2` 파싱."""
    if source in cat_map:
        return cat_map[source]
    m = _CATEGORY_HEADER.search(md)
    if m:
        return m.group(1), m.group(2)
    return None, None


def chunk_markdown(md: str) -> list[str]:
    """빈 줄 기준 블록 → 목표 길이로 병합. 표(| ... |)는 연속 유지."""
    blocks, cur = [], []
    for line in md.splitlines():
        if line.strip() == "":
            if cur:
                blocks.append("\n".join(cur))
                cur = []
        else:
            cur.append(line)
    if cur:
        blocks.append("\n".join(cur))

    chunks, buf = [], ""
    for b in blocks:
        if len(buf) + len(b) + 1 <= CHUNK_TARGET or len(buf) < CHUNK_MIN:
            buf = (buf + "\n" + b).strip()
        else:
            chunks.append(buf)
            buf = b
    if buf:
        chunks.append(buf)
    return [c for c in chunks if c.strip()]


def ingest_documents(conn, source: str, cat_map: dict | None = None):
    """파싱 마크다운을 청킹·임베딩하여 documents에 적재. 카테고리(l1/l2)도 함께 저장."""
    md_path = config.PARSED_DIR / f"{source}.md"
    md = md_path.read_text(encoding="utf-8")
    cat_l1, cat_l2 = category_for(source, md, cat_map or {})
    chunks = chunk_markdown(md)
    tag = f"{cat_l1}/{cat_l2}" if cat_l1 else "미분류"
    print(f"[documents] {source} [{tag}]: {len(chunks)}개 청크 임베딩...")

    vectors = embeddings.embed_passages(chunks)
    with conn.cursor() as cur:
        for content, emb in zip(chunks, vectors, strict=False):
            m = doc_meta(source, content, cat_l2, cat_l1)
            meta = {
                "source": source,
                "category_l1": cat_l1,
                "category_l2": cat_l2,
                "priority": m["priority"],
                "academic_year": m["academic_year"],
            }
            cur.execute(
                "INSERT INTO documents "
                "(source, category_l1, category_l2, keywords, priority, "
                " academic_year, semester, content, metadata, embedding) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    source,
                    cat_l1,
                    cat_l2,
                    m["keywords"],
                    m["priority"],
                    m["academic_year"],
                    m["semester"],
                    content,
                    json.dumps(meta),
                    emb,
                ),
            )
    print(f"[documents] {source}: {len(chunks)}건 적재 완료 (dim={len(vectors[0])})")


def ingest_all_documents(conn):
    """output/parsed/ 안의 모든 *.md 를 RAG 문서로 적재.
    팀원은 자기 문서를 parse_pdf.py로 파싱해 .md만 넣으면 자동 포함된다."""
    md_files = sorted(config.PARSED_DIR.glob("*.md"))
    if not md_files:
        print("[documents] output/parsed/*.md 없음 — 건너뜀")
        return
    cat_map = load_category_map()
    uncategorized = []
    for md_path in md_files:
        source = md_path.stem
        ingest_documents(conn, source, cat_map)
        if source not in cat_map and not _CATEGORY_HEADER.search(
            md_path.read_text(encoding="utf-8")
        ):
            uncategorized.append(source)
    if uncategorized:
        print(
            "[documents] [주의] 카테고리 미분류(NULL로 적재됨, manifest/헤더에 추가 필요): "
            + ", ".join(uncategorized)
        )


def ingest_courses(conn):
    catalog = load_json(config.STRUCTURED_DIR / "course_catalog.json")
    with conn.cursor() as cur:
        for c in catalog:
            cur.execute(
                """INSERT INTO courses
                   (교과목명, 이수구분, 학점, 이론, 실습, 개설학년, 개설학기, 트랙, 교육과정_연도)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    c["교과목명"],
                    c["이수구분"],
                    c["학점"],
                    c["이론"],
                    c["실습"],
                    str(c["개설학년"]),
                    str(c["개설학기"]),
                    c["트랙"],
                    c["교육과정_연도"],
                ),
            )
    print(f"[courses] {len(catalog)}과목 적재 완료")


def _load_graduation_by_year() -> list[dict]:
    """학번별 졸업요건 리스트(정규화 완료). 구 단일 파일로 폴백해도 동일 스키마."""
    return load_graduation_records(config.STRUCTURED_DIR)


def ingest_graduation(conn):
    grads = _load_graduation_by_year()
    with conn.cursor() as cur:
        for grad in grads:
            cur.execute(
                "INSERT INTO graduation_requirements (교육과정_연도, data) VALUES (%s, %s)",
                (grad.get("교육과정_연도"), json.dumps(grad, ensure_ascii=False)),
            )
    print(f"[graduation_requirements] {len(grads)}건 적재 완료")


def _when(c: dict) -> str:
    """과목 개설 시점 문자열. (부트캠프는 매학기/계절학기)"""
    yr, sem = c["개설학년"], c["개설학기"]
    if isinstance(sem, int):
        return f"{yr}학년 {sem}학기"
    return (f"{yr}학년 " if yr else "") + str(sem)


def _graduation_docs() -> list[tuple[str, str]]:
    """학번(입학년도)별 졸업요건 합성 문서. (content, source) 쌍으로 반환하며,
    source 제목에 년도를 넣어 doc_meta가 academic_year를 학번별로 태깅하게 한다.
    → 학번-aware 검색에서 다른 학번의 졸업요건이 섞여 인용되지 않는다."""
    out: list[tuple[str, str]] = []
    for g in _load_graduation_by_year():
        year = g["교육과정_연도"]
        전필, 전선 = g["전공필수"], g["전공선택"]
        교양 = g.get("교양", {})
        교양_str = ", ".join(f"{k} {v}학점" for k, v in 교양.items() if v is not None)
        src = f"{year} 인공지능학과 졸업요건(정형)"
        비고 = g.get("비고", "")
        out.append(
            (
                f"[졸업요건] {year}학번(입학년도 {year}년) 가천대 인공지능학과 졸업 이수학점은 "
                f"총 {g['총_졸업학점']}학점이다. 전공필수 {전필}학점, 전공선택 {전선}학점"
                + (f", {교양_str}" if 교양_str else "")
                + f"을(를) 이수해야 한다. 전공(전공필수+전공선택)은 {전필 + 전선}학점이다."
                + (f" 비고: {비고}" if 비고 else ""),
                src,
            )
        )
    return out


def _curriculum_docs() -> list[tuple[str, str]]:
    """학번(입학년도)별 전공교육과정 '요약' 문서(RAG용). 과거(2021~2025)의 트랙 구성·
    전공필수 핵심·학과명 등 학번별로 갈리는 사실을 담고, source 제목의 년도로
    academic_year를 태깅한다. (전체 과목·학점은 해당 년도 요람이 최종 근거)"""
    path = config.STRUCTURED_DIR / "curriculum_by_year.json"
    if not path.exists():
        return []
    out: list[tuple[str, str]] = []
    for cur in load_json(path):
        year = cur["교육과정_연도"]
        원문 = cur.get("학부전공_원문", "인공지능학과")
        트랙 = cur.get("트랙", {})
        트랙_str = " ".join(f"{name} 트랙({', '.join(courses)})." for name, courses in 트랙.items())
        전공필수 = ", ".join(cur.get("전공필수_핵심", []))
        비고 = cur.get("비고", "")
        src = f"{year} 인공지능학과 전공교육과정(정형)"
        out.append(
            (
                f"[교육과정] {year}학번(입학년도 {year}년) 가천대 인공지능학과"
                f"(당시 학부/전공: {원문})의 전공 트랙은 {', '.join(트랙)}(으)로 구성된다. "
                f"{트랙_str} 전공필수 핵심 과목은 {전공필수} 등이다."
                + (f" {비고}" if 비고 else ""),
                src,
            )
        )
    return out


def synthesize_structured_docs(conn):
    """정형 카탈로그/졸업요건을 '깨끗한 자연어 문서'로 합성해 RAG에 적재.
    2단 인터리빙 표에서 오는 부정확성을 제거하고 과목/학점 질의 정확도를 높인다.
    문서마다 (내용, 출처) 쌍으로 관리해 졸업요건은 학번별 년도로 태깅한다."""
    from collections import defaultdict

    catalog = load_json(config.STRUCTURED_DIR / "course_catalog.json")
    SRC_COURSE = "2026 인공지능학과 교육과정(정형)"
    docs: list[tuple[str, str]] = []  # (content, source)

    # A) 과목별 사실 문서
    for c in catalog:
        docs.append(
            (
                f"[교육과정] '{c['교과목명']}'은(는) 가천대 인공지능학과 {c['트랙']} 트랙 "
                f"{_when(c)} 개설 {c['이수구분']} 과목이며 {c['학점']}학점"
                f"(이론 {c['이론']}, 실습 {c['실습']})이다.",
                SRC_COURSE,
            )
        )

    # B) 공통 트랙 (학년,학기)별 개설 과목 (이수구분 묶음)
    grp = defaultdict(lambda: defaultdict(list))
    for c in catalog:
        if c["트랙"] == "공통" and isinstance(c["개설학기"], int):
            grp[(c["개설학년"], c["개설학기"])][c["이수구분"]].append(c["교과목명"])
    for (yr, sem), gubuns in sorted(grp.items()):
        parts = "; ".join(f"{g}: {', '.join(ns)}" for g, ns in gubuns.items())
        docs.append(
            (f"[교육과정] 인공지능학과 {yr}학년 {sem}학기 개설 과목 — {parts}.", SRC_COURSE)
        )

    # C) 트랙별 과목 목록
    for trk in ["Intelligent SW", "AIoT", "Vision & Language", "AI부트캠프"]:
        items = [f"{c['교과목명']}({_when(c)})" for c in catalog if c["트랙"] == trk]
        if items:
            docs.append(
                (f"[교육과정] 인공지능학과 {trk} 트랙 과목: " + ", ".join(items) + ".", SRC_COURSE)
            )

    # D) 이수구분별 전체 목록
    for g in ["전공필수", "전공선택", "공통필수"]:
        names = [c["교과목명"] for c in catalog if c["이수구분"] == g]
        docs.append(
            (
                f"[교육과정] 인공지능학과 {g} 과목 전체({len(names)}과목): "
                + ", ".join(names)
                + ".",
                SRC_COURSE,
            )
        )

    # E) 졸업요건 — 학번(년도)별 개별 문서 (source 제목의 년도로 academic_year 태깅)
    docs.extend(_graduation_docs())

    # F) 과거 전공교육과정 요약 — 학번(년도)별 (트랙 구성·전공필수 핵심)
    docs.extend(_curriculum_docs())

    print(f"[synth] 정형 문서 {len(docs)}건 임베딩...")
    contents = [c for c, _ in docs]
    vectors = embeddings.embed_passages(contents)
    with conn.cursor() as cur:
        for (content, source), emb in zip(docs, vectors, strict=False):
            # 접두어로 카테고리 부여: [교육과정]→course/curriculum, [졸업요건]→graduation/credit_requirement
            if content.startswith("[졸업요건]"):
                cat_l1, cat_l2 = "graduation", "credit_requirement"
            else:
                cat_l1, cat_l2 = "course", "curriculum"
            m = doc_meta(source, content, cat_l2, cat_l1)
            # 졸업요건(기준)은 핵심 근거 → priority 1. 교육과정 목록은 기본(2).
            if cat_l2 == "credit_requirement":
                m["priority"] = 1
            meta = {
                "source": source,
                "kind": "structured",
                "category_l1": cat_l1,
                "category_l2": cat_l2,
                "priority": m["priority"],
                "academic_year": m["academic_year"],
            }
            cur.execute(
                "INSERT INTO documents "
                "(source, category_l1, category_l2, keywords, priority, "
                " academic_year, semester, content, metadata, embedding) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    source,
                    cat_l1,
                    cat_l2,
                    m["keywords"],
                    m["priority"],
                    m["academic_year"],
                    m["semester"],
                    content,
                    json.dumps(meta),
                    emb,
                ),
            )
    print(f"[synth] {len(docs)}건 적재 완료")


def main():
    conn = db.connect()
    db.init_schema(conn)

    # 재적재를 위해 초기화 (idempotent)
    conn.execute("TRUNCATE documents, courses, graduation_requirements RESTART IDENTITY")

    ingest_courses(conn)
    ingest_graduation(conn)
    synthesize_structured_docs(conn)
    ingest_all_documents(conn)

    n_doc = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
    n_course = conn.execute("SELECT count(*) FROM courses").fetchone()[0]
    print(f"\n✅ 적재 완료 — documents={n_doc}, courses={n_course}")
    conn.close()


if __name__ == "__main__":
    main()
