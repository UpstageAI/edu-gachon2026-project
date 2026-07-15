-- FinBrief Supabase schema for PostgreSQL + pgvector.
-- MVP scope: subscriptions, indicators, news RAG, card cache, delivery logs, eval logs.
-- RAG decision: Upstage Solar embedding passage/query models use 4096 dimensions.
-- Keep search as exact cosine scan after date/tag filtering for the MVP.

create extension if not exists pgcrypto;
create extension if not exists vector;

create table if not exists users (
    id uuid primary key default gen_random_uuid(),
    external_user_id text not null unique,
    display_name text,
    tier text not null default 'free' check (tier in ('free', 'paid')),
    max_topics integer not null default 5 check (max_topics > 0),
    discord_webhook_url text,
    slack_webhook_url text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists topics (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    normalized_name text not null unique,
    type text not null check (type in ('indicator', 'keyword', 'sector', 'asset')),
    source_mapping jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists subscriptions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references users(id) on delete cascade,
    topic_id uuid not null references topics(id) on delete cascade,
    channel text not null check (channel in ('discord', 'slack')),
    active boolean not null default true,
    discord_channel_id text,
    created_at timestamptz not null default now(),
    unique (user_id, topic_id, channel)
);

-- 기존 배포 마이그레이션: alter table subscriptions add column if not exists discord_channel_id text;

create table if not exists indicator_values (
    id uuid primary key default gen_random_uuid(),
    indicator_id text not null,
    name text not null,
    source text not null check (source in ('fred', 'yfinance', 'ecos', 'fixture')),
    value_date date not null,
    current_value double precision not null,
    previous_value double precision,
    change_value double precision,
    change_percent double precision,
    unit text,
    missing boolean not null default false,
    raw_payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (indicator_id, value_date, source)
);

create table if not exists news_documents (
    id uuid primary key default gen_random_uuid(),
    source text not null,
    title text not null,
    url text not null unique,
    published_at timestamptz not null,
    summary text,
    tags text[] not null default '{}'::text[],
    raw_payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists news_embeddings (
    id uuid primary key default gen_random_uuid(),
    news_id uuid not null references news_documents(id) on delete cascade,
    embedding vector(4096) not null,
    embedding_model text not null,
    embedding_kind text not null default 'passage' check (embedding_kind in ('passage', 'query')),
    created_at timestamptz not null default now(),
    unique (news_id, embedding_model, embedding_kind)
);

create table if not exists cards (
    id uuid primary key default gen_random_uuid(),
    topic_id uuid not null references topics(id) on delete cascade,
    run_date date not null,
    title text not null,
    analysis jsonb not null,
    image_url text,
    report_url text,
    disclaimer text not null default '본 브리핑은 투자 조언이 아닌 참고용 정보입니다.',
    created_at timestamptz not null default now(),
    unique (topic_id, run_date)
);

create table if not exists deliveries (
    id uuid primary key default gen_random_uuid(),
    run_id text not null,
    user_id uuid not null references users(id) on delete cascade,
    topic_id uuid references topics(id) on delete set null,
    card_id uuid references cards(id) on delete set null,
    channel text not null check (channel in ('discord', 'slack')),
    status text not null check (status in ('pending', 'sent', 'failed', 'retrying', 'skipped')),
    attempts integer not null default 0 check (attempts >= 0),
    error_code text,
    error_message text,
    sent_at timestamptz,
    created_at timestamptz not null default now()
);

create table if not exists eval_runs (
    id uuid primary key default gen_random_uuid(),
    run_id text not null,
    trace_id text,
    run_date date,
    topic_id text,
    eval_name text not null,
    score double precision,
    passed boolean not null,
    result jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

alter table eval_runs add column if not exists trace_id text;
alter table eval_runs add column if not exists run_date date;
alter table eval_runs add column if not exists topic_id text;

create table if not exists report_runs (
    id uuid primary key default gen_random_uuid(),
    run_id text not null unique,
    run_date date not null,
    status text not null,
    trace_id text,
    report_id text,
    report_url text,
    disclaimer text not null default '본 브리핑은 투자 조언이 아닌 참고용 정보입니다.',
    indicators jsonb not null default '[]'::jsonb,
    missing_indicators text[] not null default '{}'::text[],
    generated_cards integer not null default 0,
    delivery_results integer not null default 0,
    eval_summary jsonb not null default '{}'::jsonb,
    errors jsonb not null default '[]'::jsonb,
    raw_payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (run_date, run_id)
);

create table if not exists report_explanations (
    id uuid primary key default gen_random_uuid(),
    run_id text not null references report_runs(run_id) on delete cascade,
    run_date date not null,
    trace_id text,
    explanation_trace_id text,
    summary text not null,
    reply text not null,
    focus_items jsonb not null default '[]'::jsonb,
    disclaimer text not null default '본 브리핑은 투자 조언이 아닌 참고용 정보입니다.',
    source text not null default 'rss_rag',
    cached boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (run_id)
);

create table if not exists card_source_explanations (
    id uuid primary key default gen_random_uuid(),
    topic_id text not null,
    run_date date not null,
    card_id text,
    trace_id text,
    explanation_trace_id text,
    topic_name text not null,
    source_summary text not null,
    reply text not null,
    sources jsonb not null default '[]'::jsonb,
    evidence_count integer not null default 0,
    disclaimer text not null default '본 브리핑은 투자 조언이 아닌 참고용 정보입니다.',
    source text not null default 'card_evidence_rag',
    cached boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (topic_id, run_date)
);

create index if not exists idx_subscriptions_user_active
    on subscriptions(user_id, active);

create index if not exists idx_indicator_values_date
    on indicator_values(value_date);

create index if not exists idx_news_documents_published_at
    on news_documents(published_at desc);

create index if not exists idx_news_documents_tags
    on news_documents using gin(tags);

create index if not exists idx_cards_topic_date
    on cards(topic_id, run_date);

create index if not exists idx_deliveries_run_status
    on deliveries(run_id, status);

create index if not exists idx_eval_runs_run_name
    on eval_runs(run_id, eval_name);

create index if not exists idx_eval_runs_trace
    on eval_runs(trace_id);

create index if not exists idx_report_runs_date
    on report_runs(run_date desc);

create index if not exists idx_report_runs_trace
    on report_runs(trace_id);

create index if not exists idx_report_explanations_date
    on report_explanations(run_date desc);

create index if not exists idx_card_source_explanations_date
    on card_source_explanations(run_date desc);

create or replace function match_news(
    query_embedding vector(4096),
    topic_tags text[] default '{}'::text[],    -- 유지: 하드필터 아님(향후 soft boost 여지)
    since timestamptz default now() - interval '3 days',
    match_count int default 40                 -- 후보 폭 확대(최종 랭킹은 app/agents/rag.py)
) returns table (
    news_id uuid,
    title text,
    source text,
    url text,
    published_at timestamptz,
    summary text,
    similarity float
)
language sql stable as $$
    select
        d.id,
        d.title,
        d.source,
        d.url,
        d.published_at,
        d.summary,
        1 - (e.embedding <=> query_embedding) as similarity
    from news_embeddings e
    join news_documents d on d.id = e.news_id
    where e.embedding_kind = 'passage'
      and d.published_at >= since               -- ★ 날짜만(하드 태그필터 제거)
    order by e.embedding <=> query_embedding     -- ★ 의미 유사도가 후보 결정
    limit match_count;
$$;
