-- 긴급재난문자 이력 테이블
-- 원본 API 필드 그대로 보존 + 통계 집계에 쓰기 편하게 분리한 파생 컬럼 추가

CREATE TABLE IF NOT EXISTS disaster_messages (
    sn              BIGINT PRIMARY KEY,        -- 원본 SN (일련번호), 중복 방지 기준
    msg_content     TEXT NOT NULL,             -- MSG_CN
    region_raw      TEXT,                      -- RCPTN_RGN_NM 원본 (trailing space 등 그대로)
    region_sido     TEXT,                      -- 파생: 시/도 (예: 경기도)
    region_sigungu  TEXT,                      -- 파생: 시/군/구 (예: 김포시)
    disaster_type   TEXT,                      -- DST_SE_NM (재해구분)
    emergency_step  TEXT,                      -- EMRG_STEP_NM (긴급단계)
    created_at      TIMESTAMP,                 -- CRT_DT 파싱 결과
    reg_date        DATE,                      -- REG_YMD 파싱 결과
    modified_date   DATE,                      -- MDFCN_YMD 파싱 결과
    is_missing_person BOOLEAN DEFAULT FALSE,   -- 전처리 단계에서 판별한 실종경보 여부 (제외 대상 표시)
    loaded_at       TIMESTAMP DEFAULT NOW()    -- 적재 시각 (파이프라인 추적용)
);

-- SQL 통계 집계(지역×월별 재난 유형 빈도)에 자주 쓰일 인덱스
CREATE INDEX IF NOT EXISTS idx_disaster_messages_region_month
    ON disaster_messages (region_sido, region_sigungu, disaster_type, created_at);

CREATE INDEX IF NOT EXISTS idx_disaster_messages_created_at
    ON disaster_messages (created_at);

-- 실종경보 등 제외 대상을 걸러낼 때 사용
CREATE INDEX IF NOT EXISTS idx_disaster_messages_is_missing
    ON disaster_messages (is_missing_person);