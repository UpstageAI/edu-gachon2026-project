-- 실제 운영 Supabase 스키마를 문서화하는 동기화 마이그레이션.
-- 0001~0002가 정의한 int(serial) PK 스키마는 실제로 적용된 적이 없고,
-- app/ingestion 파이프라인이 아래의 uuid 기반 스키마로 데이터를 적재했다.
-- 이 파일은 이미 존재하는 운영 DB에 안전하게(IF NOT EXISTS) 재적용 가능하도록 작성한다.

create extension if not exists "pgcrypto";

create table if not exists allergen_master (
    id uuid primary key default gen_random_uuid(),
    allergen_name text not null,
    category text,
    created_at timestamptz not null default now()
);

create table if not exists user_allergens (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    allergen_id uuid not null references allergen_master(id),
    created_at timestamptz not null default now()
);

create table if not exists ingredients_master (
    id uuid primary key default gen_random_uuid(),
    name text not null unique,
    ingredient_category text,
    description text,
    allergen_id uuid references allergen_master(id),
    created_at timestamptz not null default now()
);

create table if not exists ingredient_synonyms (
    id serial primary key,
    ingredient_id uuid not null references ingredients_master(id),
    synonym_name text not null
);

create table if not exists recipes (
    id uuid primary key default gen_random_uuid(),
    source_recipe_no bigint,
    name text not null,
    cooking_time integer,
    difficulty text,
    servings integer,
    category text,
    cooking_method text,
    created_at timestamptz not null default now()
);

create table if not exists recipe_ingredients (
    id uuid primary key default gen_random_uuid(),
    recipe_id uuid not null references recipes(id),
    ingredient_id uuid not null references ingredients_master(id),
    amount numeric,
    unit text,
    is_required boolean not null default true,
    notes text,
    created_at timestamptz not null default now()
);
