-- ============================================================
-- Food Compass — Supabase 초기 스키마
-- 실행 순서: Supabase > SQL Editor > 전체 붙여넣기 후 Run
-- ============================================================


-- ============================================================
-- [1] price_snapshot
--     역할: KAMIS dailyPriceByCategoryList 응답을 그대로 적재하는 원본 스냅샷
--          (Day3 설계의 price_cache를 대체 — 별도 Fallback 캐시 불필요.
--           regday/fetched_at 자체가 신선도를 말해주므로 캐시 역할까지 흡수)
--     갱신: GitHub Actions cron이 하루 1회, 부류코드(item_category_code)별로
--          전체 품목 조회 후 UPSERT (개별 품목 코드 매핑 불필요)
--     조회: 사용자 요청 경로는 이 테이블만 item_name으로 SELECT
-- ============================================================

CREATE TABLE IF NOT EXISTS price_snapshot (
    id                  BIGSERIAL   PRIMARY KEY,
    item_category_code  TEXT        NOT NULL,  -- 부류코드 (예: "200"=채소류, 5~6개 고정값)
    item_name           TEXT        NOT NULL,  -- 품목명 (예: "배추") — 사용자 질의 매칭 기준
    item_code           TEXT        NOT NULL,  -- KAMIS 품목코드 (예: "211")
    kind_name           TEXT        NOT NULL,  -- 품종명 (예: "봄(10kg(그물망 3포기))")
    kind_code           TEXT        NOT NULL,
    rank_name           TEXT        NOT NULL,  -- 등급 (예: "상품"/"중품")
    rank_code           TEXT        NOT NULL,
    unit                TEXT        NOT NULL,
    -- dpr1=당일 dpr2=1일전 dpr3=1주일전 dpr4=2주일전 dpr5=1개월전 dpr6=1년전 dpr7=평년
    -- 콤마 포함 가격 문자열("7,286") 또는 결측치("-") 그대로 저장
    dpr1                TEXT,
    dpr2                TEXT,
    dpr3                TEXT,
    dpr4                TEXT,
    dpr5                TEXT,
    dpr6                TEXT,
    dpr7                TEXT,
    regday              DATE        NOT NULL,  -- KAMIS 조회 기준일 (p_regday)
    source              TEXT        NOT NULL DEFAULT 'KAMIS',
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (item_code, kind_code, rank_code, regday)
);

-- 사용자 질의 경로 조회 기준 (item_name으로 최신 regday 찾기)
CREATE INDEX IF NOT EXISTS idx_price_snapshot_item_name
    ON price_snapshot (item_name, regday DESC);

-- 신선도 확인 및 오래된 데이터 정리용
CREATE INDEX IF NOT EXISTS idx_price_snapshot_fetched_at
    ON price_snapshot (fetched_at DESC);


-- ============================================================
-- [2] query_log
--     역할: 사용자 질의·응답 이력 저장 (디버깅·LLMOps 활용)
--     MVP 필수 아님 — Langfuse 미도입 시 간이 대체재로 활용
--     주의: 개인정보 없음 (query 텍스트만, user_id 없음)
-- ============================================================

CREATE TABLE IF NOT EXISTS query_log (
    id          BIGSERIAL   PRIMARY KEY,
    user_query  TEXT        NOT NULL,
    route       TEXT,                           -- price / knowledge / hybrid / off-topic
    items       TEXT[],                         -- 추출된 품목 목록
    answer      TEXT,
    is_fallback BOOLEAN     NOT NULL DEFAULT FALSE,  -- 캐시 Fallback 사용 여부
    latency_ms  INTEGER,                        -- 응답 소요 시간 (ms)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_query_log_created_at
    ON query_log (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_query_log_route
    ON query_log (route);


-- ============================================================
-- [3] price_gokr_items
--     역할: 참가격(data.go.kr, ProductPriceInfoService.getProductInfoSvc) 품목 마스터
--          전체 604개 중 식품 카테고리(goodSmlclsCode 앞자리 0301=신선식품, 0302=가공식품)만
--          적재 — 0303(화장품/생활용품/반려동물용품)은 애초에 제외
--     갱신: 거의 안 바뀌는 마스터 데이터 — fetch 스크립트가 매번 UPSERT만 하고 삭제는 안 함
-- ============================================================

CREATE TABLE IF NOT EXISTS price_gokr_items (
    good_id             TEXT        PRIMARY KEY,
    good_name           TEXT        NOT NULL,
    product_entp_code   TEXT,
    good_unit_div_code  TEXT,
    good_base_cnt       TEXT,
    good_smlcls_code    TEXT        NOT NULL,  -- 0301xx/0302xx만 적재 (필터링은 앱 코드에서 수행)
    good_total_cnt      TEXT,
    good_total_div_code TEXT,
    detail_mean         TEXT,
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_price_gokr_items_name
    ON price_gokr_items (good_name);

CREATE INDEX IF NOT EXISTS idx_price_gokr_items_smlcls
    ON price_gokr_items (good_smlcls_code);


-- ============================================================
-- [4] price_gokr_stores
--     역할: 참가격 판매처(매장) 마스터 (getStoreInfoSvc) — 전체 약 615개
--     갱신: 마스터 데이터 — fetch 스크립트가 매번 UPSERT만 하고 삭제는 안 함
-- ============================================================

CREATE TABLE IF NOT EXISTS price_gokr_stores (
    entp_id             TEXT        PRIMARY KEY,
    entp_name           TEXT        NOT NULL,
    entp_type_code      TEXT,
    entp_area_code      TEXT,
    area_detail_code    TEXT,
    entp_telno          TEXT,
    post_no             TEXT,
    plmk_addr_basic     TEXT,
    plmk_addr_detail    TEXT,
    road_addr_basic     TEXT,
    road_addr_detail    TEXT,
    x_map_coord         TEXT,
    y_map_coord         TEXT,
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ============================================================
-- [5] price_gokr_snapshot
--     역할: 참가격 품목×매장별 가격 관측치(getProductPriceInfoSvc) — 실제로 쌓였다
--          지워지는 시계열 데이터. price_gokr_items/stores(마스터)와 분리한 이유는
--          보관 기간 정책이 이 테이블에만 적용돼야 하기 때문(마스터는 계속 유지).
--     조사 주기: KAMIS(매일)와 달리 전국 단위로 격주(2주 간격) 동일 조사일 공유로 확인됨
--          (예: 2026-06-12, 2026-06-26엔 데이터 있고 그 사이/이후 평범한 금요일엔 0건).
--          다음 조사가 예상보다 더 늦어질 수 있음이 실측으로 확인돼서(2026-07-14 사고 —
--          retention_days=15로 방금 저장한 데이터가 전부 삭제된 적 있음), retention_days는
--          30일로 넉넉히 잡고, "테이블에 남은 가장 최신 good_inspect_day는 절대 삭제 안 함"
--          안전장치를 앱 코드(app/tools/price_gokr_snapshot.py)에 추가해서 이중으로 방어함.
-- ============================================================

CREATE TABLE IF NOT EXISTS price_gokr_snapshot (
    id                  BIGSERIAL   PRIMARY KEY,
    good_inspect_day    DATE        NOT NULL,
    entp_id             TEXT        NOT NULL,
    good_id             TEXT        NOT NULL,
    good_price          INTEGER     NOT NULL,
    good_dc_yn          TEXT,          -- 할인여부(Y/N) — 응답에 없을 때도 있어 NULL 허용
    input_dttm          TIMESTAMPTZ,
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (good_id, entp_id, good_inspect_day)
);

CREATE INDEX IF NOT EXISTS idx_price_gokr_snapshot_good_id
    ON price_gokr_snapshot (good_id, good_inspect_day DESC);

CREATE INDEX IF NOT EXISTS idx_price_gokr_snapshot_fetched_at
    ON price_gokr_snapshot (fetched_at DESC);


-- ============================================================
-- [6] price_gokr_store_regions
--     역할: 참가격 매장을 8개 권역(서울/경기도/강원도/인천/전라도/경상도/충청도/제주도)으로
--          분류 — 남도/북도는 구분 안 하고 광역시는 지리적으로 가까운 도에 합침
--          (경상도=경남+경북+부산+대구+울산, 전라도=전남+전북+광주, 충청도=충남+충북+대전+세종).
--          분류 로직: app/tools/region.py의 classify_region() — 저장된 주소(plmk_addr_basic/
--          road_addr_basic)의 첫 토큰으로 판정.
--     price_gokr_stores와 분리한 이유: 주소 원본 데이터(마스터)와 우리가 자체적으로 내린
--          분류 판단(파생 데이터)을 구분하기 위함 — 분류 기준이 바뀌어도 원본 마스터를
--          건드리지 않고 이 테이블만 재계산하면 됨.
--     갱신: 매장 주소는 거의 안 바뀌므로 fetch 스크립트가 매번 UPSERT만 함(삭제 없음).
-- ============================================================

CREATE TABLE IF NOT EXISTS price_gokr_store_regions (
    entp_id        TEXT        PRIMARY KEY,
    region         TEXT        NOT NULL,  -- 서울/경기도/강원도/인천/전라도/경상도/충청도/제주도
    classified_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_price_gokr_store_regions_region
    ON price_gokr_store_regions (region);


-- ============================================================
-- [7] price_gokr_regional_avg (VIEW)
--     역할: "같은 상품을 지역별로 나눠서 평균을 낸다"는 요구사항을 그대로 구현 —
--          예) 꽃소금의 서울 평균가, 꽃소금의 경기도 평균가 ...
--     물리 테이블이 아니라 VIEW로 만든 이유: price_gokr_snapshot(가격)·price_gokr_items
--          (품목명)·price_gokr_store_regions(지역)를 그때그때 JOIN해서 계산하므로 별도
--          갱신 스크립트 없이 항상 최신 상태를 반영함. good_inspect_day별로 그룹핑되므로
--          특정 조사일 기준 지역별 평균도 그대로 조회 가능(과거 데이터 손실 없음).
-- ============================================================

CREATE OR REPLACE VIEW price_gokr_regional_avg
WITH (security_invoker = true)  -- 뷰가 소유자 권한이 아니라 조회하는 role의 권한으로 실행되도록
                                 -- 강제 — 안 그러면 기반 테이블의 anon 차단 정책을 뷰가 우회할 수 있음
AS
SELECT
    r.region,
    i.good_id,
    i.good_name,
    sn.good_inspect_day,
    ROUND(AVG(sn.good_price), 1) AS avg_price,
    COUNT(*) AS sample_count
FROM price_gokr_snapshot sn
JOIN price_gokr_items i ON i.good_id = sn.good_id
JOIN price_gokr_store_regions r ON r.entp_id = sn.entp_id
GROUP BY r.region, i.good_id, i.good_name, sn.good_inspect_day;


-- ============================================================
-- [8] RLS(Row Level Security) 설정
--     백엔드 전용 서비스이므로 service_role 키로만 접근
--     anon / authenticated 역할 차단 (보안 기본값)
-- ============================================================

ALTER TABLE price_snapshot            ENABLE ROW LEVEL SECURITY;
ALTER TABLE query_log                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE price_gokr_items          ENABLE ROW LEVEL SECURITY;
ALTER TABLE price_gokr_stores         ENABLE ROW LEVEL SECURITY;
ALTER TABLE price_gokr_snapshot       ENABLE ROW LEVEL SECURITY;
ALTER TABLE price_gokr_store_regions  ENABLE ROW LEVEL SECURITY;

-- service_role은 RLS를 자동으로 우회하므로 별도 정책 불필요
-- 아래는 명시적 차단 (anon 키로 직접 접근 방지)
--
-- [2026-07-14 수정] CREATE POLICY는 CREATE TABLE과 달리 IF NOT EXISTS를 지원하지 않아서,
-- 이 파일을 이미 한 번 실행한 DB에 다시 통째로 실행하면 "policy already exists" 에러가 남
-- (실제로 겪음) — 항상 안전하게 재실행할 수 있도록 DROP POLICY IF EXISTS를 먼저 실행
DROP POLICY IF EXISTS "deny_anon_price_snapshot" ON price_snapshot;
CREATE POLICY "deny_anon_price_snapshot" ON price_snapshot
    FOR ALL TO anon USING (FALSE);

DROP POLICY IF EXISTS "deny_anon_query_log" ON query_log;
CREATE POLICY "deny_anon_query_log" ON query_log
    FOR ALL TO anon USING (FALSE);

DROP POLICY IF EXISTS "deny_anon_price_gokr_items" ON price_gokr_items;
CREATE POLICY "deny_anon_price_gokr_items" ON price_gokr_items
    FOR ALL TO anon USING (FALSE);

DROP POLICY IF EXISTS "deny_anon_price_gokr_stores" ON price_gokr_stores;
CREATE POLICY "deny_anon_price_gokr_stores" ON price_gokr_stores
    FOR ALL TO anon USING (FALSE);

DROP POLICY IF EXISTS "deny_anon_price_gokr_snapshot" ON price_gokr_snapshot;
CREATE POLICY "deny_anon_price_gokr_snapshot" ON price_gokr_snapshot
    FOR ALL TO anon USING (FALSE);

DROP POLICY IF EXISTS "deny_anon_price_gokr_store_regions" ON price_gokr_store_regions;
CREATE POLICY "deny_anon_price_gokr_store_regions" ON price_gokr_store_regions
    FOR ALL TO anon USING (FALSE);

-- ============================================================
-- [9] 초기 데이터
--     실데이터는 GitHub Actions cron 적재 스크립트(추후 작성)가 채움.
--     이 스키마 파일에는 샘플 INSERT 없음 — 컬럼이 원본 API 응답 그대로라
--     손으로 채운 샘플이 실데이터와 어긋날 위험이 큼.
-- ============================================================