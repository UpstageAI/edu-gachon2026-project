-- 읽기 전용 Postgres 롤: LLM이 생성한 SQL을 실행할 때 쓰는 최소 권한 계정.
-- 이 파일은 Supabase SQL Editor에서 수동으로 실행한다 (admin 자격증명을 앱/에이전트가 다루지 않기 위함).
-- 실행 후 비밀번호를 별도로 정하고, 아래 형식의 connection string을 .env의
-- DATABASE_URL_READONLY로 등록한다:
--   postgresql://ratbox_readonly:<PASSWORD>@<HOST>:5432/postgres

create role ratbox_readonly with login password 'ratbox2026';

alter role ratbox_readonly set statement_timeout = '5s';

grant usage on schema public to ratbox_readonly;
grant select on recipes, recipe_ingredients, ingredients_master to ratbox_readonly;

-- 위 3개 테이블 외에는 접근 권한을 주지 않는다 (allergen_master/user_allergens 등은
-- 앱이 supabase-py REST를 통해서만 조회하고, 이 role로는 조회하지 않는다).
