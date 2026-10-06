"""Service layer for reading the sticker catalogue.

Services contain business logic and talk to Postgres directly. They know
nothing about HTTP, `Request`/`Response`, or Jinja - routers are responsible
for that translation. Every function here takes an already-obtained asyncpg
pool (injected by the router via a FastAPI dependency) so it stays trivially
testable against a real test database.
"""

from __future__ import annotations

import asyncpg

from app.models.sticker import StickerKind, StickerOut


def sticker_from_row(row: asyncpg.Record) -> StickerOut:
    """Build a `StickerOut` from any row carrying the five sticker columns."""
    return StickerOut(
        id=row["id"],
        code=row["code"],
        kind=StickerKind(row["kind"]),
        team_code=row["team_code"],
        sort_order=row["sort_order"],
    )


async def list_all_stickers(db: asyncpg.Pool) -> list[StickerOut]:
    """Return the full sticker catalogue, ordered for grid display."""
    rows = await db.fetch(
        "select id, code, kind, team_code, sort_order from stickers order by sort_order"
    )
    return [sticker_from_row(row) for row in rows]


async def get_sticker_by_code(db: asyncpg.Pool, code: str) -> StickerOut | None:
    """Look up a single sticker by its code (e.g. "MEX7", "FWC3", "00")."""
    row = await db.fetchrow(
        "select id, code, kind, team_code, sort_order from stickers where code = $1",
        code,
    )
    return None if row is None else sticker_from_row(row)


async def count_all_stickers(db: asyncpg.Pool) -> int:
    """Total number of stickers in the catalogue (expected: 992)."""
    return int(await db.fetchval("select count(*) from stickers"))
