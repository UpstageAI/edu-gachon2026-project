-- ratbox_readonly가 recipes/recipe_ingredients/ingredients_master를 조회할 때
-- RLS(Row Level Security)에 막혀 매번 빈 결과만 반환되던 문제를 수정한다.
-- 세 테이블 모두 RLS가 켜져 있지만(0004/기존 상태) ratbox_readonly용 정책이 없어서,
-- 0005에서 GRANT SELECT를 줬어도 실제로는 행이 하나도 보이지 않았다.
-- (0005와 동일하게 Supabase SQL Editor에서 수동 실행)

create policy "allow ratbox_readonly select" on recipes
    for select to ratbox_readonly using (true);

create policy "allow ratbox_readonly select" on recipe_ingredients
    for select to ratbox_readonly using (true);

create policy "allow ratbox_readonly select" on ingredients_master
    for select to ratbox_readonly using (true);
