"""Database-backed failed-attempt limiter for login and invite-code guessing.

Counts failures per (kind, key) inside a sliding window. Stored in Postgres so
it is shared by every serverless instance (an in-memory counter would reset
whenever the platform spins up another copy of the app).
"""

from __future__ import annotations

from datetime import timedelta

import asyncpg

KIND_LOGIN_USER = "login_user"
KIND_LOGIN_IP = "login_ip"
KIND_REGISTER_IP = "register_ip"

# Rows older than this are deleted whenever a failure is recorded, so the
# table stays tiny. Far longer than any configurable window.
_RETENTION = timedelta(days=1)


async def is_blocked(
    db: asyncpg.Pool, kind: str, key: str, *, limit: int, window: timedelta
) -> bool:
    """True once `limit` or more failures were recorded inside the window."""
    count = await db.fetchval(
        """
        select count(*) from auth_failures
        where kind = $1 and key = $2 and attempted_at > now() - $3::interval
        """,
        kind,
        key,
        window,
    )
    return int(count) >= limit


async def record_failure(db: asyncpg.Pool, kind: str, key: str) -> None:
    """Record one failed attempt (and purge long-expired rows)."""
    await db.execute(
        """
        with purge as (
            delete from auth_failures where attempted_at < now() - $3::interval
        )
        insert into auth_failures (kind, key) values ($1, $2)
        """,
        kind,
        key,
        _RETENTION,
    )


async def clear(db: asyncpg.Pool, kind: str, key: str) -> None:
    """Forget a key's failures (called after a successful login)."""
    await db.execute("delete from auth_failures where kind = $1 and key = $2", kind, key)
