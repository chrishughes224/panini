"""Service layer for a user's sticker collection.

Implements the confirmed interaction model (implementation1.md, Section 3.3
and 3.6):
  - Normal tap -> `increment_sticker`: not-owned -> owned -> duplicate (qty
    keeps climbing).
  - Edit-mode tap -> `decrement_sticker`: duplicate -> owned -> not-owned,
    with the underlying row deleted once quantity would drop below 1 (kept
    consistent with lazy row creation - a quantity-0 row should never exist).
"""

from __future__ import annotations

from uuid import UUID

import gel

from app.models.collection import CollectionSummary, DuplicateEntry
from app.models.sticker import StickerKind, StickerOut, StickerWithStatus


class StickerNotFoundError(Exception):
    """Raised when a sticker code does not exist in the catalogue."""


async def get_collection_for_user(
    client: gel.AsyncIOClient, user_id: UUID
) -> list[StickerWithStatus]:
    """Return every catalogue sticker with this user's quantity (0 if none).

    Uses the `CollectionEntry` backlink from `Sticker` filtered to this user,
    coalescing to 0 for stickers the user has never tapped (lazy rows).
    """
    result = await client.query(
        """
        select Sticker {
            id, code, kind, team_code, sort_order,
            quantity := assert_single((
                select .<sticker[is CollectionEntry]
                filter .user.id = <uuid>$user_id
            ).quantity) ?? 0
        }
        order by .sort_order
        """,
        user_id=user_id,
    )
    return [
        StickerWithStatus.from_sticker_and_quantity(
            sticker=StickerOut(
                id=row.id,
                code=row.code,
                kind=StickerKind(row.kind),
                team_code=row.team_code,
                sort_order=row.sort_order,
            ),
            quantity=row.quantity,
        )
        for row in result
    ]


async def increment_sticker(
    client: gel.AsyncIOClient, user_id: UUID, sticker_code: str
) -> StickerWithStatus:
    """Normal tap: not-owned -> owned -> duplicate (quantity keeps rising).

    Uses an upsert (`unless conflict ... else update`) so the very first tap
    creates the lazy `CollectionEntry` row, and every subsequent tap just
    increments `quantity`.
    """
    sticker = await _get_sticker_by_code_or_raise(client, sticker_code)

    row = await client.query_single(
        """
        select (
            insert CollectionEntry {
                user := (select User filter .id = <uuid>$user_id),
                sticker := (select Sticker filter .code = <str>$code),
                quantity := 1,
            }
            unless conflict on ((.user, .sticker))
            else (
                update CollectionEntry
                set {
                    quantity := .quantity + 1,
                    updated_at := datetime_current(),
                }
            )
        ) { quantity }
        """,
        user_id=user_id,
        code=sticker_code,
    )
    return StickerWithStatus.from_sticker_and_quantity(sticker, row.quantity)


async def decrement_sticker(
    client: gel.AsyncIOClient, user_id: UUID, sticker_code: str
) -> StickerWithStatus:
    """Edit-mode tap: duplicate -> owned -> not-owned (undo an accidental tap).

    - quantity >= 2 -> decrement by 1.
    - quantity == 1 -> delete the row entirely (back to not-owned).
    - no row / quantity == 0 -> no-op.
    """
    sticker = await _get_sticker_by_code_or_raise(client, sticker_code)

    current = await client.query_single(
        """
        select CollectionEntry { quantity }
        filter .user.id = <uuid>$user_id and .sticker.code = <str>$code
        """,
        user_id=user_id,
        code=sticker_code,
    )
    if current is None:
        return StickerWithStatus.from_sticker_and_quantity(sticker, 0)

    if current.quantity <= 1:
        await client.query(
            """
            delete CollectionEntry
            filter .user.id = <uuid>$user_id and .sticker.code = <str>$code
            """,
            user_id=user_id,
            code=sticker_code,
        )
        return StickerWithStatus.from_sticker_and_quantity(sticker, 0)

    row = await client.query_single(
        """
        select (
            update CollectionEntry
            filter .user.id = <uuid>$user_id and .sticker.code = <str>$code
            set {
                quantity := .quantity - 1,
                updated_at := datetime_current(),
            }
        ) { quantity }
        """,
        user_id=user_id,
        code=sticker_code,
    )
    return StickerWithStatus.from_sticker_and_quantity(sticker, row.quantity)


async def list_duplicates(
    client: gel.AsyncIOClient, user_id: UUID
) -> list[DuplicateEntry]:
    """All stickers this user owns 2+ of, for the Duplicates view."""
    result = await client.query(
        """
        select CollectionEntry {
            quantity,
            sticker: { id, code, kind, team_code, sort_order }
        }
        filter .user.id = <uuid>$user_id and .quantity >= 2
        order by .sticker.sort_order
        """,
        user_id=user_id,
    )
    return [
        DuplicateEntry(
            sticker=StickerOut(
                id=row.sticker.id,
                code=row.sticker.code,
                kind=StickerKind(row.sticker.kind),
                team_code=row.sticker.team_code,
                sort_order=row.sticker.sort_order,
            ),
            quantity=row.quantity,
        )
        for row in result
    ]


async def remove_one_duplicate(
    client: gel.AsyncIOClient, user_id: UUID, sticker_code: str
) -> StickerWithStatus:
    """Trade away one duplicate: identical to `decrement_sticker`.

    Kept as a distinctly-named entry point for the Duplicates router so its
    intent ("I traded this away") is clear in that context, separate from
    the checklist's Edit-mode undo, even though the underlying operation is
    the same.
    """
    return await decrement_sticker(client, user_id, sticker_code)


async def get_collection_summary(
    client: gel.AsyncIOClient, user_id: UUID
) -> CollectionSummary:
    """Aggregate counters for the checklist page header."""
    total_stickers = await client.query_single("select count(Sticker)")
    total_collected = await client.query_single(
        "select count(CollectionEntry filter .user.id = <uuid>$user_id)",
        user_id=user_id,
    )
    total_duplicates = await client.query_single(
        """
        select sum((
            select CollectionEntry
            filter .user.id = <uuid>$user_id and .quantity >= 2
        ).quantity - 1) ?? 0
        """,
        user_id=user_id,
    )
    return CollectionSummary(
        total_stickers=total_stickers,
        total_collected=total_collected,
        total_duplicates=total_duplicates,
    )


async def _get_sticker_by_code_or_raise(
    client: gel.AsyncIOClient, sticker_code: str
) -> StickerOut:
    row = await client.query_single(
        """
        select Sticker { id, code, kind, team_code, sort_order }
        filter .code = <str>$code
        """,
        code=sticker_code,
    )
    if row is None:
        raise StickerNotFoundError(f"no sticker with code {sticker_code!r}")
    return StickerOut(
        id=row.id,
        code=row.code,
        kind=StickerKind(row.kind),
        team_code=row.team_code,
        sort_order=row.sort_order,
    )
