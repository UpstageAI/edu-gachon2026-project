-- 정책나침반 Supabase 스키마
-- 현재 앱은 온통청년/고용24 API를 매 요청마다 라이브로 호출한다.
-- 아래 테이블은 지원 소스 캐시와 채팅 세션·피드백 저장용이다.

create extension if not exists pgcrypto;

-- 고용24 국민내일배움카드 훈련과정 캐시
-- start_date/end_date/cost/capacity는 원본 API가 항상 정형 포맷을 보장하지
-- 않아 text로 저장한다 (date/numeric으로 변환 시 파싱 실패 위험).
create table if not exists training_courses (
    id uuid primary key default gen_random_uuid(),
    source text not null default 'work24_training',
    course_id text not null,
    course_round text,
    title text not null,
    institution text,
    region text,
    address text,
    start_date text,
    end_date text,
    cost text,
    actual_cost text,
    ncs_code text,
    target text,
    capacity text,
    contact text,
    detail_url text,
    institution_url text,
    raw_payload jsonb,
    fetched_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (source, course_id, course_round)
);

create index if not exists training_courses_region_idx on training_courses (region);
create index if not exists training_courses_start_date_idx on training_courses (start_date);
create index if not exists training_courses_fetched_at_idx on training_courses (fetched_at);

-- 온통청년(youthcenter) 청년정책 캐시
-- application_period은 원본 API가 자유 형식 문자열로 내려줘 text로 저장한다.
create table if not exists youth_policies (
    id uuid primary key default gen_random_uuid(),
    source text not null default 'youthcenter',
    policy_id text not null,
    title text not null,
    organization text,
    region text,
    min_age integer,
    max_age integer,
    age_restricted boolean,
    target_summary text,
    support_summary text,
    business_period text,
    business_end_date text,
    application_period text,
    application_method text,
    detail_url text,
    raw_payload jsonb,
    fetched_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (source, policy_id)
);

create index if not exists youth_policies_region_idx on youth_policies (region);
create index if not exists youth_policies_fetched_at_idx on youth_policies (fetched_at);

-- 고용24 채용 보조정보 캐시. 기본 제품 범위에는 지역을 검증할 수 있는
-- event(채용행사)와 open_recruitment(공채속보)만 저장한다.
create table if not exists recruitment_infos (
    id uuid primary key default gen_random_uuid(),
    source text not null default 'work24_recruitment',
    item_id text not null,
    item_type text not null,
    title text not null,
    company text,
    region text,
    start_date text,
    end_date text,
    summary text,
    detail_url text,
    raw_payload jsonb,
    fetched_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (source, item_id)
);

create index if not exists recruitment_infos_region_idx on recruitment_infos (region);
create index if not exists recruitment_infos_item_type_idx on recruitment_infos (item_type);
create index if not exists recruitment_infos_fetched_at_idx on recruitment_infos (fetched_at);

-- 세션 기반 대화 로그 (민감 개인정보 미저장, 데모 환경에서는 최소 로그만 유지)
create table if not exists chat_logs (
    id bigint generated always as identity primary key,
    session_id text not null,
    role text not null check (role in ('user', 'assistant')),
    content text not null,
    intent text,
    created_at timestamptz not null default now()
);

create index if not exists chat_logs_session_id_idx on chat_logs (session_id, created_at desc, id desc);

-- 구조화된 멀티턴 상태. 그래프 체크포인터 대신 이 테이블이 세션 상태의
-- 단일 저장 경계다. last_presented_candidates는 후속 설명에서만 참조한다.
create table if not exists chat_sessions (
    session_id text primary key,
    profile jsonb not null default '{}'::jsonb,
    pending_request jsonb not null default '{}'::jsonb,
    last_presented_candidates jsonb not null default '[]'::jsonb,
    last_search_plan jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- 기존 설치에 대한 비파괴 마이그레이션.
alter table chat_sessions
    add column if not exists last_presented_candidates jsonb not null default '[]'::jsonb;

alter table chat_sessions
    add column if not exists last_search_plan jsonb not null default '{}'::jsonb;
alter table youth_policies add column if not exists min_age integer;
alter table youth_policies add column if not exists max_age integer;
alter table youth_policies add column if not exists age_restricted boolean;

create index if not exists chat_sessions_updated_at_idx on chat_sessions (updated_at desc);

-- 추천 결과(말풍선 1개 = 카드 여러 개)에 대한 사용자 피드백(엄지 업/다운).
-- 같은 메시지에 다시 누르면 rating만 덮어쓴다 (session_id, message_id 유니크).
-- trace_id는 Langfuse 트레이스와 연결해 점수(score)로도 남기기 위한 참조값이다.
create table if not exists recommendation_feedback (
    session_id text not null,
    message_id text not null,
    trace_id text,
    rating text not null check (rating in ('up', 'down')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (session_id, message_id)
);

create index if not exists recommendation_feedback_session_id_idx on recommendation_feedback (session_id);

-- 대화 내용은 백엔드의 service role 키로만 접근한다.
alter table chat_logs enable row level security;
alter table chat_sessions enable row level security;
alter table recommendation_feedback enable row level security;
