"""PostgreSQL + pgvector 연결 및 스키마."""

import psycopg
from pgvector.psycopg import register_vector

from app import config


def connect():
    """pgvector 등록된 psycopg 연결 반환."""
    conn = psycopg.connect(config.DATABASE_URL, autocommit=True)
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    register_vector(conn)
    return conn


def init_schema(conn):
    """RAG 문서/과목/졸업요건 테이블 생성."""
    dim = config.EMBED_DIM
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS documents (
            id            BIGSERIAL PRIMARY KEY,
            source        TEXT NOT NULL,
            page          INT,
            category      TEXT,
            category_l1   TEXT,
            category_l2   TEXT,
            keywords      TEXT[],
            priority      INTEGER DEFAULT 2,
            academic_year INTEGER,
            semester      TEXT,
            is_active     BOOLEAN DEFAULT TRUE,
            content       TEXT NOT NULL,
            metadata      JSONB DEFAULT '{{}}'::jsonb,
            embedding     VECTOR({dim})
        )
        """
    )
    # 기존 DB(컬럼 없이 생성된 경우) 대응: 컬럼을 안전하게 추가한다. (멘토링 결과 §7)
    conn.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS category_l1 TEXT")
    conn.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS category_l2 TEXT")
    conn.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS keywords TEXT[]")
    conn.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS priority INTEGER DEFAULT 2")
    conn.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS academic_year INTEGER")
    conn.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS semester TEXT")
    conn.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE")
    # 필터·정렬용 인덱스
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_documents_category ON documents (category_l1, category_l2)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_active ON documents (is_active)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS courses (
            id            BIGSERIAL PRIMARY KEY,
            교과목명       TEXT NOT NULL,
            이수구분       TEXT,
            학점          INT,
            이론          INT,
            실습          INT,
            개설학년       TEXT,
            개설학기       TEXT,
            트랙          TEXT,
            교육과정_연도   INT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS graduation_requirements (
            id            BIGSERIAL PRIMARY KEY,
            교육과정_연도   INT,
            data          JSONB NOT NULL
        )
        """
    )
    # 리마인드 예약 테이블(런타임 운영 테이블)은 ingest 데이터와 무관하므로
    # ensure_runtime_schema로 분리해 앱 시작(lifespan)에서도 보장한다.
    ensure_runtime_schema(conn)
    # 주의: pgvector HNSW/IVFFlat 인덱스는 최대 2000차원까지만 지원한다.
    # Upstage 임베딩은 4096차원이고 문서 수가 적으므로, 인덱스 없이
    # 정확(exact) 코사인 검색(<=>)을 사용한다. (데이터가 커지면 halfvec 전환 고려)


def ensure_runtime_schema(conn):
    """앱 구동에 필요한 '운영 테이블'만 생성(idempotent).

    지식 테이블(documents/courses/graduation_requirements)은 ingest 데이터가
    있어야 의미가 있어 ingest(init_schema)가 만들지만, reminder_requests는
    ingest와 무관한 런타임 상태 저장소다. ingest를 돌리지 않았거나 스키마가
    뒤처진 DB에 앱을 붙여도 리마인드가 조용히 실패하지 않도록, 앱 시작 시
    (main.lifespan)에서도 이 함수를 호출해 테이블 존재를 보장한다.
    체크포인터 테이블을 시작 시 setup()으로 만드는 것과 같은 취지다.
    """
    # 이메일 리마인드 예약 (Phase 2). remind_at까지는 scheduler가 대기 목록으로만
    # 조회하고, 실제 발송은 scheduler가 Resend API 호출 후 status를 갱신한다.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reminder_requests (
            id           BIGSERIAL PRIMARY KEY,
            session_id   TEXT,
            email        TEXT NOT NULL,
            content      TEXT NOT NULL,
            remind_at    TIMESTAMP NOT NULL,
            status       TEXT NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending', 'sent', 'failed')),
            error        TEXT,
            created_at   TIMESTAMP DEFAULT NOW(),
            sent_at      TIMESTAMP
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_reminder_requests_pending "
        "ON reminder_requests (remind_at) WHERE status = 'pending'"
    )
