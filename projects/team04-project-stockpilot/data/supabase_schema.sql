-- StockPilot RAG schema
-- Supabase SQL Editor에서 한 번 실행합니다.

create extension if not exists vector;

create table if not exists public.documents (
  id bigserial primary key,
  source_id text,
  chunk_index integer,
  content text not null,
  embedding vector(4096),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- 실습용 documents 테이블이 이미 존재하는 경우에도 안전하게 열을 추가합니다.
alter table public.documents add column if not exists source_id text;
alter table public.documents add column if not exists chunk_index integer;
alter table public.documents add column if not exists updated_at timestamptz default now();

create unique index if not exists documents_source_chunk_idx
  on public.documents (source_id, chunk_index);

create index if not exists documents_metadata_idx
  on public.documents using gin (metadata);

create or replace function public.match_documents(
  query_embedding vector(4096),
  match_count integer default 4,
  match_threshold float default 0.3,
  filter_corp_code text default null,
  filter_source_type text default null
)
returns table (
  id bigint,
  content text,
  metadata jsonb,
  similarity float
)
language sql
stable
as $$
  select
    d.id,
    d.content,
    d.metadata,
    (1 - (d.embedding <=> query_embedding))::float as similarity
  from public.documents d
  where
    d.embedding is not null
    and (filter_corp_code is null or d.metadata->>'corp_code' = filter_corp_code)
    and (
      filter_source_type is null
      or d.metadata->>'source_type' = filter_source_type
    )
    and 1 - (d.embedding <=> query_embedding) >= match_threshold
  order by d.embedding <=> query_embedding
  limit least(greatest(match_count, 1), 50);
$$;

alter table public.documents enable row level security;

-- 적재 스크립트는 backend 전용 service-role 키를 사용합니다.
-- 프론트엔드에서 직접 읽어야 할 때만 별도의 SELECT 정책을 추가하세요.

create table if not exists public.watchlists (
  id bigserial primary key,
  session_id text not null,
  ticker text not null,
  name text,
  created_at timestamptz not null default now(),
  unique (session_id, ticker)
);

alter table public.watchlists enable row level security;

-- 관심 종목 저장도 backend의 service-role 키를 통해서만 수행합니다.

create table if not exists public.document_facts (
  id bigserial primary key,
  source_id text not null unique,
  facts jsonb not null default '{}'::jsonb,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists document_facts_metadata_idx
  on public.document_facts using gin (metadata);

alter table public.document_facts enable row level security;

-- Structured glossary table.
-- Long documents stay in public.documents(pgvector), but dictionary-style
-- investment terms are stored here for exact term/alias lookup.
create table if not exists public.glossary_terms (
  id bigserial primary key,
  term text not null unique,
  definition text not null,
  category text,
  aliases text[] not null default '{}'::text[],
  difficulty text not null default 'beginner',
  example text,
  source_url text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists glossary_terms_term_lower_idx
  on public.glossary_terms (lower(term));

create index if not exists glossary_terms_aliases_idx
  on public.glossary_terms using gin (aliases);

create index if not exists glossary_terms_metadata_idx
  on public.glossary_terms using gin (metadata);

alter table public.glossary_terms enable row level security;

-- Glossary rows are written by the backend with the service-role key.

-- Information Extract 결과도 backend의 service-role 키로만 저장합니다.

-- ============================================================
-- 사용자 계정 (로그인) & 즐겨찾기 연결
-- ============================================================
create table if not exists public.users (
  id bigserial primary key,
  username text not null unique,
  password_hash text not null,
  created_at timestamptz not null default now()
);

alter table public.users enable row level security;

-- 즐겨찾기를 사용자 계정에 연결 (기존 session_id 기반과 공존)
alter table public.watchlists
  add column if not exists user_id bigint references public.users(id) on delete cascade;
alter table public.watchlists alter column session_id drop not null;
create unique index if not exists watchlists_user_ticker_idx
  on public.watchlists (user_id, ticker) where user_id is not null;

-- 로그인 사용자별 대화 저장 (제목·메시지·인사이트 전체를 data jsonb로)
create table if not exists public.conversations (
  id text primary key,
  user_id bigint not null references public.users(id) on delete cascade,
  data jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);
create index if not exists idx_conversations_user
  on public.conversations (user_id, updated_at desc);
alter table public.conversations enable row level security;
