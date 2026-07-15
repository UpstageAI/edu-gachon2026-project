"""RAG(정책 검색) 엔진: 저장소 정책 문서를 검색해 리뷰에 참고 자료로 넣는 단계.

RAG = Retrieval-Augmented Generation. "관련 문서를 먼저 찾아서(retrieval) 모델에게
같이 건네주는" 방식이다. 여기서는 저장소의 마크다운 정책 문서를 다룬다.

이 파일이 하는 일은 크게 두 단계다.
1) split_policy_markdown(): 정책 문서(.md)를 제목(#) 기준으로 잘라 검색 단위인
   PolicyChunk("조각") 목록으로 만든다.
2) rank_policy_chunks(): PR 내용(제목/파일/patch)과 각 조각이 단어를 얼마나 겹치는지
   (lexical overlap, 단어 겹침)로 점수를 매겨 관련도 높은 순으로 top_k개를 고른다.

임베딩 벡터가 아닌 "단어 겹침"만 쓰는 가벼운 방식이라, 외부 모델 없이 로컬/테스트에서
바로 동작한다. LocalPolicyIndex(파일에서 직접 읽기)와 PostgresPolicyIndex(DB에 저장)
두 백엔드가 있고, create_policy_index()가 설정에 따라 알맞은 것을 만들어 준다.
"""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

from backend.app.core.config import Settings
from backend.app.core.schemas import PolicyChunk, ReviewRequest

# re.compile(...)은 정규식(패턴)을 미리 만들어 두는 것이다. 여기서는 텍스트에서
# "단어"를 뽑는 데 쓴다. [\w./-]+ = 글자/숫자/밑줄과 . / - 가 이어진 덩어리.
TOKEN_PATTERN = re.compile(r"[\w./-]+", re.UNICODE)
# 위에서 뽑은 단어를 다시 _ . / - 기준으로 쪼갤 때 쓰는 패턴(예: auth/jwt -> auth, jwt).
TOKEN_SPLIT_PATTERN = re.compile(r"[_./-]+")
# 정책 문서로 인정할 파일 패턴(glob). 마크다운, CODEOWNERS, PR 템플릿 등.
POLICY_GLOBS = ("*.md", "**/*.md", "CODEOWNERS", ".github/pull_request_template.md")
# 저장소의 공식 AI 리뷰 정책 파일 경로. 검색에서 특별 취급(가산점)한다.
REPOSITORY_POLICY_PATH = ".github/ai-review-policy.md"
# 규범(지켜야 할 규칙)이 아닌 소개/범위성 섹션 제목. 이런 섹션은 조각으로 만들지 않는다.
NON_NORMATIVE_SECTION_TITLES = {"적용 범위", "scope", "overview"}
# 파일 경로/내용에 이 단어가 있으면 해당 정책 유형(policy_type)으로 분류한다.
# (경로힌트, 정책유형) 쌍의 튜플이며, 위에서부터 먼저 걸리는 것이 우선한다.
POLICY_TYPE_PATH_HINTS = (
    ("security", "security"),
    ("api", "api"),
    ("test", "test"),
    ("performance", "performance"),
    ("maintainability", "maintainability"),
    ("observability", "observability"),
    ("reliability", "reliability"),
    ("github", "architecture"),
    ("workflow", "architecture"),
    ("style", "style"),
    ("architecture", "architecture"),
)


def _tokens(text: str) -> set[str]:
    """텍스트를 소문자 단어들의 집합(set)으로 바꾼다. 점수 계산의 기본 재료.

    set(집합)은 중복이 없고 순서가 없는 모음이라, 나중에 & (교집합)으로 "겹치는
    단어"를 빠르게 구할 수 있다. 함수 이름의 밑줄(_)은 이 파일 내부용이라는 표시다.
    """
    tokens: set[str] = set()
    # findall(...)은 패턴에 맞는 모든 조각을 리스트로 돌려준다.
    for raw_token in TOKEN_PATTERN.findall(text):
        normalized = raw_token.lower()
        # 너무 짧은 단어(1~2글자)는 노이즈라 버린다.
        if len(normalized) > 2:
            tokens.add(normalized)
        # 복합어(auth/jwt 등)를 조각으로도 쪼개 넣어 겹칠 확률을 높인다.
        # update(...)는 여러 값을 한꺼번에 집합에 추가한다(제너레이터 표현식 사용).
        tokens.update(
            part
            for part in TOKEN_SPLIT_PATTERN.split(normalized)
            if len(part) > 2
        )
    return tokens


def _policy_type(path: Path, content: str) -> str:
    """정책 조각의 유형(security/api/test 등)을 경로와 내용으로 추정한다.

    공식 정책 파일(REPOSITORY_POLICY_PATH)은 경로가 항상 같으므로 내용을 먼저 보고,
    그 외 문서는 경로를 먼저 본다. 어느 힌트에도 안 걸리면 "general".
    """
    lowered_content = content[:500].lower()  # 앞부분 500자만 훑어 본다.
    lowered_path = str(path).lower()
    # 삼항식으로 검사 순서를 정한다: 공식 정책이면 (내용, 경로), 아니면 (경로, 내용).
    sources = (
        (lowered_content, lowered_path)
        if lowered_path == REPOSITORY_POLICY_PATH
        else (lowered_path, lowered_content)
    )
    for source in sources:
        for hint, policy_type in POLICY_TYPE_PATH_HINTS:
            if hint in source:
                return policy_type
    return "general"


def split_policy_markdown(
    source_path: str | Path,
    content: str,
    max_chars: int = 1800,
) -> list[PolicyChunk]:
    """마크다운 정책 문서 하나를 제목(#) 단위의 PolicyChunk 목록으로 자른다.

    한 조각이 너무 길면(max_chars 초과) 검색/주입에 부담되므로 여러 조각으로 다시 나눈다.
    max_chars=1800: 한 조각의 최대 글자 수(기본값).
    """
    source_path = Path(source_path)  # 문자열로 와도 Path 객체로 통일한다.
    chunks: list[PolicyChunk] = []
    section_title = source_path.name  # 첫 제목이 나오기 전 기본 섹션 이름은 파일명.
    buffer: list[str] = []  # 현재 섹션에서 모으는 중인 줄들.

    # flush()는 지금까지 buffer에 모인 줄들을 하나의(또는 여러) 조각으로 확정하는
    # 내부 함수다. 바깥 변수(chunks/buffer/section_title)를 그대로 공유해 쓴다.
    def flush() -> None:
        if not buffer:
            return
        text = "\n".join(buffer).strip()
        if not text:
            buffer.clear()
            return
        # 규범이 아닌 소개성 섹션은 조각으로 만들지 않고 버린다.
        if section_title.strip().lower() in NON_NORMATIVE_SECTION_TITLES:
            buffer.clear()
            return
        # 너무 길면 max_chars 크기로 잘라 앞부분을 먼저 조각으로 넣고 나머지를 이어 처리.
        while len(text) > max_chars:
            chunks.append(
                PolicyChunk(
                    source_path=str(source_path),
                    section_title=section_title,
                    content=text[:max_chars],
                    policy_type=_policy_type(source_path, f"{section_title}\n{text}"),
                )
            )
            text = text[max_chars:]
        # 남은(또는 원래 짧았던) 텍스트를 마지막 조각으로 넣는다.
        chunks.append(
            PolicyChunk(
                source_path=str(source_path),
                section_title=section_title,
                content=text,
                policy_type=_policy_type(source_path, f"{section_title}\n{text}"),
            )
        )
        buffer.clear()

    # 문서를 한 줄씩 훑으며, 제목 줄(#로 시작)을 만나면 직전 섹션을 확정(flush)한다.
    for line in content.splitlines():
        if line.startswith("#"):
            flush()
            # 앞의 # 기호들을 떼고 제목 텍스트만 남긴다. 비어 있으면 파일명으로.
            section_title = line.lstrip("#").strip() or source_path.name
            continue
        buffer.append(line)
    flush()  # 마지막 섹션도 잊지 않고 확정한다.
    return chunks


def _query_tokens(request: ReviewRequest) -> set[str]:
    """검색 질의(query) 쪽 단어 집합을 만든다. 즉 "이 PR이 무엇에 관한가"의 단어들.

    제목 + 바뀐 파일 경로 + 체크 요약 + patch 앞부분을 한 덩어리로 합쳐 단어화한다.
    긴 텍스트는 [:1000]처럼 앞부분만 잘라 성능과 노이즈를 조절한다.
    """
    query_parts = [
        request.pull_request.title,
        " ".join(changed_file.path for changed_file in request.changed_files),
        " ".join(check.summary[:1000] for check in request.checks),
        # 파일이 많을 수 있어 앞의 10개만, patch도 1200자까지만 본다.
        " ".join(changed_file.patch[:1200] for changed_file in request.changed_files[:10]),
    ]
    return _tokens("\n".join(query_parts))


def rank_policy_chunks(
    chunks: list[PolicyChunk],
    request: ReviewRequest,
    top_k: int,
    policy_types: set[str] | None = None,
) -> list[PolicyChunk]:
    """모든 조각에 관련도 점수를 매겨 상위 top_k개를 골라 돌려준다(RAG의 핵심).

    policy_types: 이 유형에 속한 조각만 보고 싶을 때 넘긴다(None이면 전부 대상).
    점수는 "질의와 겹치는 단어 수"를 기반으로 하며, 조각이 길수록 유리해지는 것을
    막기 위해 조각 단어 수의 제곱근으로 나눠 정규화한다.
    """
    if not chunks:
        return []

    query_tokens = _query_tokens(request)
    scored: list[PolicyChunk] = []
    for chunk in chunks:
        is_repository_policy = chunk.source_path == REPOSITORY_POLICY_PATH
        # 유형 필터가 있으면 안 맞는 조각은 건너뛴다. 단, 공식 정책은 항상 포함.
        if policy_types and chunk.policy_type not in policy_types and not is_repository_policy:
            continue
        chunk_tokens = _tokens(f"{chunk.source_path} {chunk.section_title} {chunk.content}")
        # & 는 교집합: 질의와 조각 양쪽에 다 있는 단어들만 남긴다(겹치는 단어).
        overlap = query_tokens & chunk_tokens
        if not overlap:
            continue
        # 점수 = 겹친 단어 수 / sqrt(조각 단어 수). 긴 조각이 무조건 유리해지지 않게 함.
        score = len(overlap) / math.sqrt(max(len(chunk_tokens), 1))
        # 공식 저장소 정책은 +10점 가산해 사실상 항상 상위로 끌어올린다.
        if is_repository_policy:
            score += 10.0
        scored.append(
            PolicyChunk(
                source_path=chunk.source_path,
                section_title=chunk.section_title,
                content=chunk.content,
                policy_type=chunk.policy_type,
                score=round(score, 4),
            )
        )

    if not scored:
        return []
    # 점수 높은 순으로 정렬해 앞에서 top_k개만. key=lambda로 "무엇 기준 정렬"을 지정한다.
    return sorted(scored, key=lambda item: item.score, reverse=True)[:top_k]


class LocalPolicyIndex:
    """Small local RAG index used for MVP and tests.

    The production-ready path is to replace this with pgvector while keeping the
    same retrieve contract.
    """

    def __init__(self, policy_root: Path) -> None:
        # policy_root: 정책 문서들이 들어 있는 최상위 폴더 경로.
        self.policy_root = policy_root

    def _candidate_files(self) -> list[Path]:
        """POLICY_GLOBS 패턴에 맞는 정책 파일 경로들을 모아 정렬해 돌려준다."""
        if not self.policy_root.exists():
            return []
        # set으로 모으는 이유: 여러 glob 패턴이 같은 파일을 중복으로 잡을 수 있어서.
        files: set[Path] = set()
        for pattern in POLICY_GLOBS:
            for path in self.policy_root.glob(pattern):
                if path.is_file():
                    files.add(path)
        return sorted(files)  # 항상 같은 순서를 보장한다.

    def load_chunks(self) -> list[PolicyChunk]:
        """모든 후보 파일을 읽어 조각(PolicyChunk) 목록으로 펼친다."""
        chunks: list[PolicyChunk] = []
        for path in self._candidate_files():
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                # 깨진 문자가 있어도 무시하고 읽어 프로그램이 죽지 않게 한다.
                content = path.read_text(encoding="utf-8", errors="ignore")
            # 조각의 source_path는 루트 기준 상대 경로로 저장한다(환경 독립적).
            relative_path = path.relative_to(self.policy_root)
            # extend는 리스트에 여러 원소를 한꺼번에 이어 붙인다.
            chunks.extend(split_policy_markdown(relative_path, content))
        return chunks

    def has_policy(self) -> bool:
        """참고할 정책 문서가 하나라도 있는지 여부(라우팅의 RAG 사용 판단에 쓰임)."""
        return bool(self._candidate_files())

    def sync(self) -> dict[str, int]:
        """인덱스를 갱신하고 문서/조각 개수를 알려 준다(로컬은 읽기만 하면 끝)."""
        chunks = self.load_chunks()
        return {
            "indexed_documents": len(self._candidate_files()),
            "indexed_chunks": len(chunks),
        }

    def search(
        self,
        request: ReviewRequest,
        top_k: int = 5,
        policy_types: set[str] | None = None,
    ) -> list[PolicyChunk]:
        """이 요청과 관련된 정책 조각 상위 top_k개를 검색한다(외부에서 부르는 진입점)."""
        chunks = self.load_chunks()
        return rank_policy_chunks(chunks, request, top_k, policy_types)


# LocalPolicyIndex를 상속(물려받음)해 같은 사용법(search 등)을 유지하되,
# 조각을 파일이 아니라 PostgreSQL 데이터베이스에 저장/조회하도록 바꾼 버전.
class PostgresPolicyIndex(LocalPolicyIndex):
    def __init__(self, policy_root: Path, database_url: str) -> None:
        super().__init__(policy_root)  # 부모의 __init__을 먼저 실행(policy_root 설정).
        self.database_url = database_url
        self._schema_ready = False  # 테이블 준비가 끝났는지 기억하는 플래그.

    def _connect(self):
        try:
            import psycopg  # DB 접속 라이브러리. 없을 수도 있어 함수 안에서 import.
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise RuntimeError("psycopg is not installed. Run `pip install -e .`.") from exc
        return psycopg.connect(self.database_url)

    def ensure_schema(self) -> None:
        """정책 조각을 담을 테이블이 없으면 만든다. 한 번만 하면 되므로 플래그로 건너뛴다."""
        if self._schema_ready:
            return
        # with ... as : 블록이 끝나면 연결/커서를 자동으로 정리(close)해 주는 문법.
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS policy_chunks (
                        id BIGSERIAL PRIMARY KEY,
                        source_path TEXT NOT NULL,
                        section_title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        policy_type TEXT NOT NULL,
                        content_hash TEXT NOT NULL UNIQUE,
                        embedding VECTOR(1536),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_policy_chunks_source_path
                    ON policy_chunks (source_path)
                    """
                )
        self._schema_ready = True

    def sync(self) -> dict[str, int]:
        """파일에서 읽은 조각들을 DB에 통째로 다시 채워 넣는다(기존 내용 삭제 후 삽입)."""
        self.ensure_schema()
        chunks = self.load_chunks()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM policy_chunks")
                for chunk in chunks:
                    # content_hash: 조각 내용의 지문(고유값). 같은 내용이 중복 저장되는
                    # 것을 막고(UNIQUE), 아래 ON CONFLICT로 갱신 판단에 쓴다.
                    content_hash = hashlib.sha256(
                        "\n".join(
                            [
                                chunk.source_path,
                                chunk.section_title,
                                chunk.policy_type,
                                chunk.content,
                            ]
                        ).encode("utf-8")
                    ).hexdigest()
                    cur.execute(
                        """
                        INSERT INTO policy_chunks (
                            source_path,
                            section_title,
                            content,
                            policy_type,
                            content_hash
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (content_hash) DO UPDATE SET
                            source_path = EXCLUDED.source_path,
                            section_title = EXCLUDED.section_title,
                            content = EXCLUDED.content,
                            policy_type = EXCLUDED.policy_type,
                            updated_at = now()
                        """,
                        (
                            chunk.source_path,
                            chunk.section_title,
                            chunk.content,
                            chunk.policy_type,
                            content_hash,
                        ),
                    )
        return {
            "indexed_documents": len(self._candidate_files()),
            "indexed_chunks": len(chunks),
        }

    def _load_indexed_chunks(self) -> list[PolicyChunk]:
        """DB에 저장된 조각들을 읽어 PolicyChunk 목록으로 되살린다."""
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT source_path, section_title, content, policy_type
                    FROM policy_chunks
                    ORDER BY id
                    """
                )
                # fetchall()은 결과 행들을 돌려주고, 각 행(row)에서 컬럼을 순서로 꺼낸다.
                return [
                    PolicyChunk(
                        source_path=row[0],
                        section_title=row[1],
                        content=row[2],
                        policy_type=row[3],
                    )
                    for row in cur.fetchall()
                ]

    def has_policy(self) -> bool:
        """DB에 조각이 있는지 확인한다. 비어 있는데 파일은 있으면 먼저 sync 후 판단."""
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM policy_chunks")
                count = int(cur.fetchone()[0])
        if count == 0 and self._candidate_files():
            return self.sync()["indexed_chunks"] > 0
        return count > 0

    def search(
        self,
        request: ReviewRequest,
        top_k: int = 5,
        policy_types: set[str] | None = None,
    ) -> list[PolicyChunk]:
        """DB에서 조각을 읽어 검색한다. 아직 안 채워졌으면 한 번 sync 후 다시 읽는다."""
        chunks = self._load_indexed_chunks()
        if not chunks and self._candidate_files():
            self.sync()
            chunks = self._load_indexed_chunks()
        return rank_policy_chunks(chunks, request, top_k, policy_types)


def create_policy_index(settings: Settings) -> LocalPolicyIndex:
    """설정(settings)을 보고 알맞은 정책 인덱스 구현을 만들어 주는 공장(factory) 함수.

    RAG_BACKEND=postgres 면 DB 버전을, 아니면 로컬 파일 버전을 쓴다.
    반환 타입이 부모 LocalPolicyIndex라, 부르는 쪽은 어느 구현인지 몰라도 똑같이 쓴다.
    """
    if settings.rag_backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is required when RAG_BACKEND=postgres")
        return PostgresPolicyIndex(settings.policy_root, settings.database_url)
    return LocalPolicyIndex(settings.policy_root)
