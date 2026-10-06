from __future__ import annotations

from uuid import UUID

import asyncpg
import pytest

from app.models.sticker import StickerStatus
from app.models.user import UserCreate
from app.services import auth_service, collection_service
from app.services.collection_service import StickerNotFoundError


async def _user(pool: asyncpg.Pool, name: str = "alice") -> UUID:
    user = await auth_service.register_user(
        pool, UserCreate(username=name, email=f"{name}@example.com", password="correct-horse-1")
    )
    return user.id


async def _entry_count(pool: asyncpg.Pool, user_id: UUID) -> int:
    return int(await pool.fetchval("select count(*) from collection_entries where user_id = $1", user_id))


# --- increment ------------------------------------------------------------

async def test_increment_walks_not_owned_owned_duplicate(pool: asyncpg.Pool) -> None:
    uid = await _user(pool)

    first = await collection_service.increment_sticker(pool, uid, "MEX1")
    second = await collection_service.increment_sticker(pool, uid, "MEX1")
    third = await collection_service.increment_sticker(pool, uid, "MEX1")

    assert (first.quantity, first.status) == (1, StickerStatus.OWNED)
    assert (second.quantity, second.status) == (2, StickerStatus.DUPLICATE)
    assert third.quantity == 3
    assert await _entry_count(pool, uid) == 1  # upsert, never a second row


async def test_increment_unknown_code_raises_and_writes_nothing(pool: asyncpg.Pool) -> None:
    uid = await _user(pool)

    with pytest.raises(StickerNotFoundError):
        await collection_service.increment_sticker(pool, uid, "NOPE1")

    assert await _entry_count(pool, uid) == 0


# --- decrement / undo -----------------------------------------------------

async def test_decrement_walks_back_and_deletes_row_at_zero(pool: asyncpg.Pool) -> None:
    uid = await _user(pool)
    for _ in range(3):
        await collection_service.increment_sticker(pool, uid, "MEX1")

    after_one = await collection_service.decrement_sticker(pool, uid, "MEX1")
    after_two = await collection_service.decrement_sticker(pool, uid, "MEX1")
    after_three = await collection_service.decrement_sticker(pool, uid, "MEX1")

    assert after_one.quantity == 2 and after_one.status is StickerStatus.DUPLICATE
    assert after_two.quantity == 1 and after_two.status is StickerStatus.OWNED
    assert after_three.quantity == 0 and after_three.status is StickerStatus.NOT_OWNED
    assert await _entry_count(pool, uid) == 0  # a quantity-0 row must never exist


async def test_decrement_when_not_owned_is_a_noop(pool: asyncpg.Pool) -> None:
    uid = await _user(pool)

    result = await collection_service.decrement_sticker(pool, uid, "MEX1")

    assert result.quantity == 0
    assert await _entry_count(pool, uid) == 0


async def test_decrement_unknown_code_raises(pool: asyncpg.Pool) -> None:
    uid = await _user(pool)

    with pytest.raises(StickerNotFoundError):
        await collection_service.decrement_sticker(pool, uid, "NOPE1")


async def test_remove_one_duplicate_behaves_like_decrement(pool: asyncpg.Pool) -> None:
    uid = await _user(pool)
    await collection_service.increment_sticker(pool, uid, "BRA5")
    await collection_service.increment_sticker(pool, uid, "BRA5")

    result = await collection_service.remove_one_duplicate(pool, uid, "BRA5")

    assert result.quantity == 1 and result.status is StickerStatus.OWNED


# --- reading --------------------------------------------------------------

async def test_get_collection_covers_every_sticker_in_order(pool: asyncpg.Pool) -> None:
    uid = await _user(pool)
    await collection_service.increment_sticker(pool, uid, "MEX1")
    await collection_service.increment_sticker(pool, uid, "MEX1")
    await collection_service.increment_sticker(pool, uid, "ARG3")

    items = await collection_service.get_collection_for_user(pool, uid)

    assert len(items) == 992
    assert [i.sticker.sort_order for i in items] == sorted(i.sticker.sort_order for i in items)
    by_code = {i.sticker.code: i.quantity for i in items}
    assert by_code["MEX1"] == 2
    assert by_code["ARG3"] == 1
    assert by_code["MEX2"] == 0
    assert sum(1 for i in items if i.quantity) == 2


async def test_collections_are_isolated_between_users(pool: asyncpg.Pool) -> None:
    alice = await _user(pool, "alice")
    bob = await _user(pool, "bob")
    await collection_service.increment_sticker(pool, alice, "MEX1")

    bobs = await collection_service.get_collection_for_user(pool, bob)

    assert all(i.quantity == 0 for i in bobs)
    assert (await collection_service.get_collection_summary(pool, bob)).total_collected == 0


async def test_get_sticker_status_is_read_only(pool: asyncpg.Pool) -> None:
    uid = await _user(pool)

    before = await collection_service.get_sticker_status(pool, uid, "MEX1")
    assert before is not None and before.status is StickerStatus.NOT_OWNED
    assert await _entry_count(pool, uid) == 0  # checking must never add

    await collection_service.increment_sticker(pool, uid, "MEX1")
    after = await collection_service.get_sticker_status(pool, uid, "MEX1")
    assert after is not None and after.status is StickerStatus.OWNED


async def test_get_sticker_status_unknown_code_is_none(pool: asyncpg.Pool) -> None:
    uid = await _user(pool)

    assert await collection_service.get_sticker_status(pool, uid, "NOPE1") is None


# --- aggregates -----------------------------------------------------------

async def test_summary_counts_collected_and_spares(pool: asyncpg.Pool) -> None:
    uid = await _user(pool)
    empty = await collection_service.get_collection_summary(pool, uid)
    assert (empty.total_stickers, empty.total_collected, empty.total_duplicates) == (992, 0, 0)

    for code, taps in {"MEX1": 3, "MEX2": 1, "ARG3": 2}.items():
        for _ in range(taps):
            await collection_service.increment_sticker(pool, uid, code)

    summary = await collection_service.get_collection_summary(pool, uid)

    assert summary.total_collected == 3  # distinct stickers owned
    assert summary.total_duplicates == (3 - 1) + (2 - 1)  # spare copies only


async def test_count_owned_for_team(pool: asyncpg.Pool) -> None:
    uid = await _user(pool)
    for code in ("MEX1", "MEX2", "MEX2", "BRA1"):
        await collection_service.increment_sticker(pool, uid, code)

    assert await collection_service.count_owned_for_team(pool, uid, "MEX") == 2
    assert await collection_service.count_owned_for_team(pool, uid, "BRA") == 1
    assert await collection_service.count_owned_for_team(pool, uid, "ARG") == 0


async def test_concurrent_taps_never_lose_an_increment(pool: asyncpg.Pool) -> None:
    """Upsert is atomic: N simultaneous first-taps must end at exactly N."""
    import asyncio

    uid = await _user(pool)

    await asyncio.gather(
        *(collection_service.increment_sticker(pool, uid, "MEX1") for _ in range(8))
    )

    status = await collection_service.get_sticker_status(pool, uid, "MEX1")
    assert status is not None and status.quantity == 8
    assert await _entry_count(pool, uid) == 1
