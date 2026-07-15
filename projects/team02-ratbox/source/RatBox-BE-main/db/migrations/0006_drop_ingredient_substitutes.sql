-- 0003(ingredient_substitutes)의 정리 마이그레이션. 대체재 판단이 LLM 즉석 판단으로
-- 바뀌면서 이 테이블은 코드 어디에서도 참조하지 않는다(schema.sql 참고).
-- 0003은 실제 운영 DB에 적용된 적이 없지만, 혹시 로컬/스테이징에 남아있는 경우를 대비해
-- IF EXISTS로 안전하게 제거한다. 0005와 동일하게 Supabase SQL Editor에서 수동 실행한다.

drop table if exists ingredient_substitutes;
