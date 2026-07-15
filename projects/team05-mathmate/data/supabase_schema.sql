-- MathMate Supabase 스키마
-- 사용법: Supabase 대시보드 > SQL Editor 에 붙여넣고 [Run].
-- (백엔드는 service_role 키로 접속 → RLS를 우회하므로 별도 정책 없이도 읽기/쓰기 가능.
--  RLS는 켜 두어, 혹시 publishable 키가 노출돼도 정답이 직접 조회되지 않게 막는다.)

-- 1) 문제은행 -------------------------------------------------------------
create table if not exists public.problems (
    id             text primary key,          -- 예: p_0001
    grade          int,
    semester       int,
    unit           text,
    difficulty     text,                       -- 쉬움 | 중간 | 어려움
    problem        text not null,
    answer         text not null,              -- 정답(학생/프론트에 절대 노출 금지)
    hint1          text,
    hint2          text,
    hint3          text,
    solution_steps jsonb default '[]'::jsonb,
    next_question  text,
    source         text,                       -- orca | generated
    created_at     timestamptz default now()
);

-- 조회 속도용 인덱스
create index if not exists idx_problems_unit  on public.problems (grade, semester, unit);
create index if not exists idx_problems_diff  on public.problems (difficulty);

alter table public.problems enable row level security;
-- (정책을 만들지 않음 = anon(publishable) 키로는 접근 불가. 백엔드 service 키만 접근.)

-- 2) 학습 진척도 ----------------------------------------------------------
-- 핵심 KPI = '힌트 사용량'. 학생×문제 단위로 누적한다.
create table if not exists public.progress (
    id             bigint generated always as identity primary key,
    student_id     text not null,
    problem_id     text not null references public.problems(id),
    attempts       int  not null default 0,    -- 이 문제에 시도한 턴 수
    hints_used     int  not null default 0,    -- 받은 힌트 개수(누적) = 핵심 지표
    max_hint_level int  not null default 0,    -- 도달한 최고 힌트 단계(1~3)
    solved         boolean not null default false,
    updated_at     timestamptz default now(),
    unique (student_id, problem_id)            -- 학생×문제당 한 행(upsert 기준)
);

create index if not exists idx_progress_student on public.progress (student_id);

alter table public.progress enable row level security;

-- 3) 마이그레이션: 프로필(users)·진척도(attempts) 보강 (2회차 멘토링 피드백 반영) --------
-- users: 동명이인+비밀번호 조합 대신, 학생이 직접 정하는 고유 아이디(login_id)로 식별.
-- 기존 행은 login_id가 NULL이라 UNIQUE 제약에 안 걸림(NULL은 여러 개 허용).
alter table public.users add column if not exists login_id text unique;

-- attempts: 난이도별 정답률 계산을 위해 문제 난이도를 같이 저장.
alter table public.attempts add column if not exists difficulty text;

-- progress: 힌트를 다 쓰고 포기(공개)한 문제인지 기록 — 이미 끝난 문제를 다시 고르면
-- 힌트 단계를 리셋하고 새로 시작하기 위해 필요(안 그러면 재도전해도 곧장 정답이 공개됨).
alter table public.progress add column if not exists revealed boolean not null default false;
