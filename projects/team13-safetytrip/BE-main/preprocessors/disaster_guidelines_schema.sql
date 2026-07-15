-- 재난 국민행동요령 테이블 (RAG용, pgvector)
-- Solar Embedding (solar-embedding-1-large) 기준 4096차원

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS disaster_guidelines (
    id              BIGSERIAL PRIMARY KEY,   -- 고유 ID 필드가 API에 없어서 자동생성
    content         TEXT NOT NULL,           -- actRmks (행동요령 본문)
    contents_url    TEXT,                    -- contentsUrl
    safety_cate1    TEXT,                    -- 카테고리1코드 (예: 01=자연재난, 02=사회재난)
    safety_cate2    TEXT,                    -- 카테고리2코드
    safety_cate3    TEXT,                    -- 카테고리3코드
    safety_cate4    TEXT,                    -- 카테고리4코드
    safety_cate_nm1 TEXT,                    -- 카테고리1명칭 (예: 자연재난/사회재난)
    safety_cate_nm2 TEXT,                    -- 카테고리2명칭 (예: 호우, 해양오염사고 등 구체적 재난유형)
    safety_cate_nm3 TEXT,                    -- 카테고리3명칭 (예: 발생전/발생시/발생후)
    source_dataset  TEXT NOT NULL,           -- '자연재난' / '사회재난' / '생활안전' (승인된 것부터 채워짐)
    embedding       vector(4096),            -- solar-embedding-1-large-passage 임베딩 결과
    loaded_at       TIMESTAMP DEFAULT NOW()
);

-- 카테고리로 필터링할 때 쓸 인덱스
CREATE INDEX IF NOT EXISTS idx_disaster_guidelines_cate_nm2
    ON disaster_guidelines (safety_cate_nm2);

CREATE INDEX IF NOT EXISTS idx_disaster_guidelines_source
    ON disaster_guidelines (source_dataset);

-- 참고: Solar 임베딩(4096차원)은 pgvector HNSW/ivfflat 인덱스의 최대 지원 차원(2000)을 넘어서
-- 벡터 인덱스를 생성할 수 없음. 현재 데이터 규모(수백~수천 건)에서는 인덱스 없이도
-- 순차 스캔(cosine distance 직접 계산)으로 충분히 빠르게 동작함.
-- 데이터가 수만 건 이상으로 커지면 그때 halfvec 타입이나 차원 축소를 검토.
--
-- CREATE INDEX IF NOT EXISTS idx_disaster_guidelines_embedding
--     ON disaster_guidelines USING hnsw (embedding vector_cosine_ops);