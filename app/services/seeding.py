"""Populate the canonical sticker catalogue.

Idempotent: existing stickers are matched by their unique `code` and only have
`sort_order` refreshed, so it is safe to re-run after tweaking
`catalogue_data.py` without creating duplicate rows.
"""

from __future__ import annotations

import asyncpg

from app.services.catalogue_data import build_catalogue, expected_total_stickers

_UPSERT = """
insert into stickers (code, kind, team_code, sort_order)
select * from unnest($1::text[], $2::sticker_kind[], $3::text[], $4::int[])
on conflict (code) do update set sort_order = excluded.sort_order
"""


async def seed_catalogue(pool: asyncpg.Pool) -> int:
    """Upsert the full catalogue; return the resulting sticker count.

    Raises `RuntimeError` if the count does not match the catalogue definition.
    """
    rows = build_catalogue()
    await pool.execute(
        _UPSERT,
        [row.code for row in rows],
        [row.kind.value for row in rows],
        [row.team_code for row in rows],
        [row.sort_order for row in rows],
    )
    total: int = await pool.fetchval("select count(*) from stickers")
    expected = expected_total_stickers()
    if total != expected:
        raise RuntimeError(f"Expected {expected} stickers but found {total}.")
    return total
