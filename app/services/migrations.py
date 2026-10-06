"""Minimal forward-only SQL migration runner.

Applies `app/migrations/NNN_*.sql` files in filename order, each inside its
own transaction, recording applied versions in `schema_migrations` so re-runs
are no-ops. Deliberately tiny (no Alembic) - the schema is four tables.
"""

from __future__ import annotations

from pathlib import Path

import asyncpg

from app.services.db import AnyConnection

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"

_ENSURE_TABLE = """
create table if not exists schema_migrations (
    version    text primary key,
    applied_at timestamptz not null default now()
)
"""


async def apply_migrations(conn: AnyConnection) -> list[str]:
    """Apply any pending migrations; return the versions applied this call."""
    await conn.execute(_ENSURE_TABLE)
    done = {row["version"] for row in await conn.fetch("select version from schema_migrations")}

    applied: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.stem in done:
            continue
        async with conn.transaction():
            await conn.execute(path.read_text(encoding="utf-8"))
            await conn.execute("insert into schema_migrations (version) values ($1)", path.stem)
        applied.append(path.stem)
    return applied
