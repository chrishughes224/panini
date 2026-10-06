"""Service layer for a user's sticker collection.

Implements the confirmed interaction model (implementation1.md, Section 3.3
and 3.6):
  - Normal tap -> `increment_sticker`: not-owned -> owned -> duplicate (qty
    keeps climbing).
  - Edit-mode tap -> `decrement_sticker`: duplicate -> owned -> not-owned,
    with the underlying row deleted once quantity would drop below 1 (kept
    consistent with lazy row creation - a quantity-0 row should never exist).

Every mutation is a single SQL statement (one round trip, atomic), which
matters once the database is remote rather than on localhost.
"""

from __future__ import annotations

from uuid import UUID

import asyncpg

from app.models.collection import CollectionSummary
from app.models.sticker import StickerWithStatus
from app.services.sticker_service import sticker_from_row


class StickerNotFoundError(Exception):
    """Raised when a sticker code does not exist in the catalogue."""


def _with_status(row: asyncpg.Record) -> StickerWithStatus:
    return StickerWithStatus.from_sticker_and_quantity(
        sticker=sticker_from_row(row), quantity=row["quantity"]
    )


async def get_collection_for_user(db: asyncpg.Pool, user_id: UUID) -> list[StickerWithStatus]:
    """Return every catalogue sticker with this user's quantity (0 if none).

    A left join against this user's `collection_entries`, coalescing to 0 for
    stickers the user has never tapped (lazy rows).
    """
    rows = await db.fetch(
        """
        select s.id, s.code, s.kind, s.team_code, s.sort_order,
               coalesce(ce.quantity, 0)::int as quantity
        from stickers s
        left join collection_entries ce
               on ce.sticker_id = s.id and ce.user_id = $1
        order by s.sort_order
        """,
        user_id,
    )
    return [_with_status(row) for row in rows]


async def get_sticker_status(
    db: asyncpg.Pool, user_id: UUID, sticker_code: str
) -> StickerWithStatus | None:
    """Look up one sticker's current owned/not-owned status for this user,
    without changing anything - used by the "Check" quick-lookup, as
    opposed to `increment_sticker`/`decrement_sticker` which both mutate.

    Returns None if `sticker_code` doesn't match any catalogue sticker.
    """
    row = await db.fetchrow(
        """
        select s.id, s.code, s.kind, s.team_code, s.sort_order,
               coalesce(ce.quantity, 0)::int as quantity
        from stickers s
        left join collection_entries ce
               on ce.sticker_id = s.id and ce.user_id = $1
        where s.code = $2
        """,
        user_id,
        sticker_code,
    )
    return None if row is None else _with_status(row)


async def increment_sticker(
    db: asyncpg.Pool, user_id: UUID, sticker_code: str
) -> StickerWithStatus:
    """Normal tap: not-owned -> owned -> duplicate (quantity keeps rising).

    An upsert, so the very first tap creates the lazy `collection_entries`
    row and every subsequent tap just increments `quantity`.
    """
    row = await db.fetchrow(
        """
        with s as (
            select id, code, kind, team_code, sort_order
            from stickers where code = $2
        ),
        up as (
            insert into collection_entries (user_id, sticker_id, quantity)
            select $1, id, 1 from s
            on conflict (user_id, sticker_id) do update
                set quantity = collection_entries.quantity + 1,
                    updated_at = now()
            returning sticker_id, quantity
        )
        select s.id, s.code, s.kind, s.team_code, s.sort_order, up.quantity::int as quantity
        from s join up on up.sticker_id = s.id
        """,
        user_id,
        sticker_code,
    )
    if row is None:
        raise StickerNotFoundError(f"no sticker with code {sticker_code!r}")
    return _with_status(row)


async def decrement_sticker(
    db: asyncpg.Pool, user_id: UUID, sticker_code: str
) -> StickerWithStatus:
    """Edit-mode tap: duplicate -> owned -> not-owned (undo an accidental tap).

    - quantity >= 2 -> decrement by 1.
    - quantity == 1 -> delete the row entirely (back to not-owned).
    - no row / quantity == 0 -> no-op.

    The two data-modifying CTEs match disjoint rows (quantity > 1 vs <= 1),
    so exactly one of them can fire for a given entry.
    """
    row = await db.fetchrow(
        """
        with s as (
            select id, code, kind, team_code, sort_order
            from stickers where code = $2
        ),
        dec as (
            update collection_entries ce
            set quantity = ce.quantity - 1, updated_at = now()
            from s
            where ce.sticker_id = s.id and ce.user_id = $1 and ce.quantity > 1
            returning ce.quantity
        ),
        del as (
            delete from collection_entries ce
            using s
            where ce.sticker_id = s.id and ce.user_id = $1 and ce.quantity <= 1
            returning ce.id
        )
        select s.id, s.code, s.kind, s.team_code, s.sort_order,
               coalesce((select quantity from dec), 0)::int as quantity
        from s
        """,
        user_id,
        sticker_code,
    )
    if row is None:
        raise StickerNotFoundError(f"no sticker with code {sticker_code!r}")
    return _with_status(row)


async def remove_one_duplicate(
    db: asyncpg.Pool, user_id: UUID, sticker_code: str
) -> StickerWithStatus:
    """Trade away one duplicate: identical to `decrement_sticker`.

    Kept as a distinctly-named entry point for the Duplicates router so its
    intent ("I traded this away") is clear in that context, separate from
    the checklist's Edit-mode undo, even though the underlying operation is
    the same.
    """
    return await decrement_sticker(db, user_id, sticker_code)


async def count_owned_for_team(db: asyncpg.Pool, user_id: UUID, team_code: str) -> int:
    """How many of this team's stickers the user owns (quantity >= 1).

    Used to refresh a single team's progress tile after a tap/quick-add,
    without re-fetching the whole 992-sticker collection.
    """
    return int(
        await db.fetchval(
            """
            select count(*)
            from stickers s
            join collection_entries ce
              on ce.sticker_id = s.id and ce.user_id = $1 and ce.quantity >= 1
            where s.team_code = $2
            """,
            user_id,
            team_code,
        )
    )


async def get_collection_summary(db: asyncpg.Pool, user_id: UUID) -> CollectionSummary:
    """Aggregate counters for the checklist page header."""
    row = await db.fetchrow(
        """
        select
            (select count(*) from stickers)::int                               as total_stickers,
            (select count(*) from collection_entries where user_id = $1)::int  as total_collected,
            (select coalesce(sum(quantity - 1), 0) from collection_entries
              where user_id = $1 and quantity >= 2)::int                       as total_duplicates
        """,
        user_id,
    )
    assert row is not None
    return CollectionSummary(
        total_stickers=row["total_stickers"],
        total_collected=row["total_collected"],
        total_duplicates=row["total_duplicates"],
    )
