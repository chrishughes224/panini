-- Initial Postgres schema, ported 1:1 from the original Gel schema
-- (dbschema/default.gel). Semantics preserved:
--   * quantity: lazy rows only, never below 1 (0 = no row at all).
--   * (user, sticker) is unique, so a tap upserts.
--   * username and email are each unique (case-sensitive, as in Gel).
-- UUID primary keys are kept (rather than serials) so rows imported from the
-- old Gel database keep their exact ids, and existing session cookies stay
-- valid across the cut-over.

create type sticker_kind as enum ('Special', 'Generic', 'Promo', 'Team');

create table users (
    id            uuid primary key default gen_random_uuid(),
    username      text not null unique,
    email         text not null unique,
    password_hash text not null,
    created_at    timestamptz not null default now()
);

create table sessions (
    id         uuid primary key default gen_random_uuid(),
    token      text not null unique,
    user_id    uuid not null references users (id) on delete cascade,
    created_at timestamptz not null default now(),
    expires_at timestamptz not null
);
create index sessions_user_id_idx on sessions (user_id);

create table stickers (
    id         uuid primary key default gen_random_uuid(),
    code       text not null unique,          -- e.g. "MEX7", "FWC3", "CC12", "00"
    kind       sticker_kind not null,
    team_code  text,                          -- null for Special/Generic/Promo
    sort_order integer not null               -- deterministic grid rendering order
);
create index stickers_sort_order_idx on stickers (sort_order);
create index stickers_team_code_idx on stickers (team_code);

create table collection_entries (
    id         uuid primary key default gen_random_uuid(),
    user_id    uuid not null references users (id) on delete cascade,
    sticker_id uuid not null references stickers (id) on delete cascade,
    quantity   smallint not null default 1 check (quantity >= 1),
    updated_at timestamptz not null default now(),
    unique (user_id, sticker_id)
);
