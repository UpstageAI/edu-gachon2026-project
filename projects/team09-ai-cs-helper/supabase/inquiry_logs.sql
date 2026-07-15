create table if not exists inquiry_logs (
    log_id uuid primary key default gen_random_uuid(),
    inquiry_id uuid not null
        references inquiries(inquiry_id)
        on delete cascade,
    sequence bigint generated always as identity,
    stage text not null,
    event text not null,
    title text not null,
    message text,
    attempt integer,
    duration_ms integer,
    data jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists inquiry_logs_inquiry_sequence_idx
on inquiry_logs (inquiry_id, sequence);
