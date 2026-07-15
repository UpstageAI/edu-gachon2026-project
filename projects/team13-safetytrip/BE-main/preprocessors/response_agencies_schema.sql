-- 재난대응기관(행정기관 코드 체계) 테이블
-- 주의: 이 API는 전화번호가 없는 "행정기관 코드/계층" 테이블임.
-- 실제 연락처는 disaster_type_phone_map.py의 DISASTER_TYPE_PHONE_MAP 사용.

CREATE TABLE IF NOT EXISTS response_agencies (
    cntrm_inst_cd   TEXT,               -- 대응기관코드
    srch_type       TEXT,               -- 검색유형
    sclsf_cd        TEXT,               -- 소분류코드
    rnkn            INTEGER,            -- 서열
    whol_inst_nm    TEXT,               -- 전체기관명 (예: 부산광역시 부산진구)
    inst_nm         TEXT,               -- 기관명 (예: 부산진구)
    cycl            INTEGER,            -- 차수
    hghrk_inst_cd   TEXT,               -- 최상위기관코드
    shghrk_inst_cd  TEXT,               -- 차상위기관코드
    rprs_inst_cd    TEXT,               -- 대표기관코드
    lclsf_cd        TEXT,               -- 대분류코드
    loaded_at       TIMESTAMP DEFAULT NOW()
);

-- 지역명으로 기관을 찾을 때 쓸 인덱스 (disaster_messages의 region_sido/region_sigungu와 매칭)
CREATE INDEX IF NOT EXISTS idx_response_agencies_inst_nm
    ON response_agencies (inst_nm);

CREATE INDEX IF NOT EXISTS idx_response_agencies_whol_inst_nm
    ON response_agencies (whol_inst_nm);