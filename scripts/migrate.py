"""Apply pending SQL migrations to the database in DATABASE_URL.

Run with:
    uv run python -m scripts.migrate
"""

from __future__ import annotations

import asyncio

import asyncpg

from app.config import get_settings
from app.services.migrations import apply_migrations


async def main() -> None:
    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is not set.")
    conn = await asyncpg.connect(settings.database_url, statement_cache_size=0)
    try:
        applied = await apply_migrations(conn)
    finally:
        await conn.close()
    print(f"Applied migrations: {applied or 'none (already up to date)'}")


if __name__ == "__main__":
    asyncio.run(main())
