-- ingredients_master.ingredient_category(text 자유 입력)를 정식 룩업 테이블 참조로 바꾼다.
-- 기존 ingredient_category 값은 대부분 "기타"로 뭉쳐 있어 자동 매핑이 의미가 없으므로,
-- 이 마이그레이션은 스키마만 만들고 데이터 이전은 하지 않는다. 실제 카테고리 목록과
-- 재료별 매핑은 운영자가 Supabase에서 직접 채운다.
-- 이 파일은 Supabase SQL Editor에서 수동으로 실행한다 (0005/0007과 동일한 관례).

create table if not exists ingredients_category (
    id uuid primary key default gen_random_uuid(),
    name text not null unique,
    created_at timestamptz not null default now()
);

alter table ingredients_master
    add column if not exists category_id uuid references ingredients_category(id);

-- 기존 ingredient_category 텍스트 컬럼은 드롭하지 않는다. 수기 매핑을 끝내기 전까지
-- 참고 데이터로 남겨두고, 매핑이 끝난 뒤 운영자가 별도로 드롭한다.

-- generate_sql_prompt.py가 생성하는 SQL이 이 테이블도 조회할 수 있어야 하므로
-- 0005_readonly_role.sql이 만든 읽기 전용 롤의 권한을 확장한다.
grant select on ingredients_category to ratbox_readonly;
