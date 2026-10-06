"""Postgres connection pool factory (asyncpg).

Kept isolated in its own module so services depend on a single, easily
overridable entry point rather than constructing pools themselves.

The pool is created lazily on first use and bound to the running event loop.
If a different loop is running later (tests, or a serverless runtime that
recycles its loop) the stale pool is discarded and a fresh one created, rather
than failing with "attached to a different loop".
"""

from __future__ import annotations

import asyncio

import asyncpg
from asyncpg.pool import PoolConnectionProxy

from app.config import get_settings

# A connection obtained either directly or from a pool.
AnyConnection = asyncpg.Connection[asyncpg.Record] | PoolConnectionProxy[asyncpg.Record]

_pool: asyncpg.Pool | None = None
_pool_loop: asyncio.AbstractEventLoop | None = None


async def create_pool(dsn: str, max_size: int = 5) -> asyncpg.Pool:
    """Create a pool configured to be safe behind PgBouncer / Neon's pooler.

    `statement_cache_size=0` disables prepared-statement caching, which is
    incompatible with PgBouncer in transaction-pooling mode. Idle connections
    are recycled after 30s so we never hold one that Neon has suspended.
    """
    return await asyncpg.create_pool(
        dsn=dsn,
        min_size=0,
        max_size=max_size,
        statement_cache_size=0,
        max_inactive_connection_lifetime=30,
    )


async def get_pool() -> asyncpg.Pool:
    """Return the process-wide pool for the running event loop."""
    global _pool, _pool_loop

    loop = asyncio.get_running_loop()
    if _pool is not None and _pool_loop is loop:
        return _pool

    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it to .env (or the environment); on "
            "Neon use the pooled connection string."
        )

    new_pool = await create_pool(settings.database_url, settings.db_pool_max_size)
    if _pool is not None and _pool_loop is loop:
        # Lost a race with a concurrent first request; keep the winner.
        await new_pool.close()
        return _pool

    _pool, _pool_loop = new_pool, loop
    return new_pool


async def close_pool() -> None:
    """Close the process-wide pool, if one was created."""
    global _pool, _pool_loop
    if _pool is not None:
        pool, _pool, _pool_loop = _pool, None, None
        await pool.close()
