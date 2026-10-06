from __future__ import annotations

import asyncpg

from app.models.sticker import StickerKind
from app.services import sticker_service
from app.services.catalogue_data import expected_total_stickers


async def test_catalogue_has_992_stickers(pool: asyncpg.Pool) -> None:
    assert await sticker_service.count_all_stickers(pool) == 992 == expected_total_stickers()


async def test_list_all_is_ordered_for_grid_display(pool: asyncpg.Pool) -> None:
    stickers = await sticker_service.list_all_stickers(pool)

    orders = [s.sort_order for s in stickers]
    assert orders == sorted(orders)
    assert stickers[0].code == "00"
    assert len({s.code for s in stickers}) == len(stickers)


async def test_get_by_code_team_sticker(pool: asyncpg.Pool) -> None:
    sticker = await sticker_service.get_sticker_by_code(pool, "MEX7")

    assert sticker is not None
    assert sticker.kind is StickerKind.TEAM
    assert sticker.team_code == "MEX"
    assert sticker.subtitle is None


async def test_get_by_code_non_team_sticker_has_no_team(pool: asyncpg.Pool) -> None:
    sticker = await sticker_service.get_sticker_by_code(pool, "CC12")

    assert sticker is not None
    assert sticker.kind is StickerKind.PROMO
    assert sticker.team_code is None


async def test_get_by_code_unknown_is_none(pool: asyncpg.Pool) -> None:
    assert await sticker_service.get_sticker_by_code(pool, "ZZZ99") is None


async def test_kind_counts_match_catalogue(pool: asyncpg.Pool) -> None:
    rows = await pool.fetch("select kind::text, count(*) n from stickers group by kind")
    counts = {r["kind"]: r["n"] for r in rows}

    assert counts["Team"] == 48 * 20
    assert counts["Promo"] == 12
    assert sum(counts.values()) == 992
