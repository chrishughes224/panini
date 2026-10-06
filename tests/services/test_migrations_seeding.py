from __future__ import annotations

import asyncpg

from app.services.migrations import apply_migrations
from app.services.seeding import seed_catalogue


async def test_migrations_are_idempotent(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        assert await apply_migrations(conn) == []  # fixture already applied them

    versions = [r["version"] for r in await pool.fetch("select version from schema_migrations")]
    assert versions == ["001_initial"]


async def test_seeding_twice_does_not_duplicate_stickers(pool: asyncpg.Pool) -> None:
    assert await seed_catalogue(pool) == 992
    assert await seed_catalogue(pool) == 992


async def test_schema_rejects_zero_quantity_rows(pool: asyncpg.Pool) -> None:
    import pytest

    user_id = await pool.fetchval(
        "insert into users (username, email, password_hash) values ('u', 'u@example.com', 'x') returning id"
    )
    sticker_id = await pool.fetchval("select id from stickers limit 1")

    with pytest.raises(asyncpg.CheckViolationError):
        await pool.execute(
            "insert into collection_entries (user_id, sticker_id, quantity) values ($1, $2, 0)",
            user_id,
            sticker_id,
        )
