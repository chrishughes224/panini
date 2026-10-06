from __future__ import annotations

from datetime import timedelta

import asyncpg

from app.services import rate_limit

WINDOW = timedelta(minutes=15)


async def _blocked(pool: asyncpg.Pool, key: str = "k", kind: str = "login_user", limit: int = 3) -> bool:
    return await rate_limit.is_blocked(pool, kind, key, limit=limit, window=WINDOW)


async def test_blocks_exactly_at_the_limit(pool: asyncpg.Pool) -> None:
    for _ in range(2):
        await rate_limit.record_failure(pool, "login_user", "k")
    assert not await _blocked(pool)

    await rate_limit.record_failure(pool, "login_user", "k")
    assert await _blocked(pool)


async def test_failures_outside_the_window_do_not_count(pool: asyncpg.Pool) -> None:
    await pool.execute(
        "insert into auth_failures (kind, key, attempted_at) "
        "select 'login_user', 'k', now() - interval '20 minutes' from generate_series(1, 5)"
    )

    assert not await _blocked(pool)


async def test_keys_and_kinds_are_independent(pool: asyncpg.Pool) -> None:
    for _ in range(3):
        await rate_limit.record_failure(pool, "login_user", "alice")

    assert await _blocked(pool, "alice")
    assert not await _blocked(pool, "bob")
    assert not await _blocked(pool, "alice", kind="login_ip")


async def test_clear_forgets_only_that_key(pool: asyncpg.Pool) -> None:
    for key in ("alice", "bob"):
        for _ in range(3):
            await rate_limit.record_failure(pool, "login_user", key)

    await rate_limit.clear(pool, "login_user", "alice")

    assert not await _blocked(pool, "alice")
    assert await _blocked(pool, "bob")


async def test_old_rows_are_purged_when_recording(pool: asyncpg.Pool) -> None:
    await pool.execute(
        "insert into auth_failures (kind, key, attempted_at) "
        "values ('login_user', 'ancient', now() - interval '3 days')"
    )

    await rate_limit.record_failure(pool, "login_user", "fresh")

    assert await pool.fetchval("select count(*) from auth_failures where key = 'ancient'") == 0
    assert await pool.fetchval("select count(*) from auth_failures where key = 'fresh'") == 1
