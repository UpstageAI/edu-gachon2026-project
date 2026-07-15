-- 전체 스키마 스냅샷 (문서용). 실제 적용은 migrations/ 참고.
-- 0001~0002는 초기 설계(int PK)로, 실제 운영 DB에는 적용되지 않았다.
-- 0004가 실제 운영 스키마(uuid PK)를 문서화하며 0001~0002를 대체한다.
-- 0003(ingredient_substitutes)은 실제 DB에 존재하지 않고, 대체재 판단이 LLM 기반으로 바뀌며 사용하지 않는다.
-- 0006은 혹시 남아있을 ingredient_substitutes를 정리하는 1회성 마이그레이션이라 스냅샷에는 포함하지 않는다.
\i migrations/0004_schema_sync.sql
\i migrations/0005_readonly_role.sql
\i migrations/0007_readonly_rls_policy.sql
\i migrations/0008_ingredients_category.sql
