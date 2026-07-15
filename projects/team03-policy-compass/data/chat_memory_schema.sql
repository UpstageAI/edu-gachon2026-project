-- 정책나침반 대화 메모리 전용 스키마
-- Supabase SQL Editor에서 이 파일만 실행해도 멀티턴 메모리를 사용할 수 있다.

create table if not exists chat_logs (
    id bigint generated always as identity primary key,
    session_id text not null,
    role text not null check (role in ('user', 'assistant')),
    content text not null,
    intent text,
    created_at timestamptz not null default now()
);

create index if not exists chat_logs_session_id_idx
    on chat_logs (session_id, created_at desc, id desc);

create table if not exists chat_sessions (
    session_id text primary key,
    profile jsonb not null default '{}'::jsonb,
    pending_request jsonb not null default '{}'::jsonb,
    -- 후속 설명에 필요한 제목·공식 필드·URL만 저장하며 raw payload는 저장하지 않는다.
    last_presented_candidates jsonb not null default '[]'::jsonb,
    -- 후보가 0건이어도 후속 필터 수정(예: 지역 제한 해제)에 사용할 직전 검색 계획.
    last_search_plan jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- 기존 설치에 대한 비파괴 마이그레이션.
alter table chat_sessions
    add column if not exists last_presented_candidates jsonb not null default '[]'::jsonb;

alter table chat_sessions
    add column if not exists last_search_plan jsonb not null default '{}'::jsonb;

create index if not exists chat_sessions_updated_at_idx
    on chat_sessions (updated_at desc);

-- 대화 내용은 브라우저의 publishable/anon 키로 읽거나 쓸 수 없게 한다.
-- 백엔드의 SUPABASE_KEY에는 secret/service_role 키를 설정하며 service role은 RLS를 우회한다.
alter table chat_logs enable row level security;
alter table chat_sessions enable row level security;
