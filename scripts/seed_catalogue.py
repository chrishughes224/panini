"""One-off script to populate the canonical 992-sticker catalogue.

Run with:
    uv run python scripts/seed_catalogue.py

Idempotent (see `app.services.seeding`), so safe to re-run.
"""

from __future__ import annotations

import asyncio

from app.config import get_settings
from app.services.db import create_pool
from app.services.seeding import seed_catalogue


async def main() -> None:
    settings = get_settings()
    pool = await create_pool(settings.database_url, max_size=2)
    try:
        total = await seed_catalogue(pool)
    finally:
        await pool.close()
    print(f"Seeded catalogue: {total} stickers in DB.")


if __name__ == "__main__":
    asyncio.run(main())
