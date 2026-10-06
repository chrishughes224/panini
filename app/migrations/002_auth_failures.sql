-- Failed-attempt log used for brute-force protection (login and invite-code
-- guessing). Kept in the database rather than memory so the limit holds across
-- serverless instances. Rows are short-lived; old ones are purged on write.

create table auth_failures (
    id           bigint generated always as identity primary key,
    kind         text not null,           -- 'login_user' | 'login_ip' | 'register_ip'
    key          text not null,           -- lower-cased username, or client address
    attempted_at timestamptz not null default now()
);
create index auth_failures_lookup_idx on auth_failures (kind, key, attempted_at);
