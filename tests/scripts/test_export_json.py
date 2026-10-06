from __future__ import annotations

import json
import stat
from pathlib import Path

import asyncpg

from app.models.user import UserCreate
from app.services import auth_service, collection_service
from scripts.export_json import export_json
from scripts.import_gel_export import import_export


async def _snapshot(pool: asyncpg.Pool) -> dict[str, list[tuple[object, ...]]]:
    """Everything user-owned, in a comparable form."""
    def rows(records: list[asyncpg.Record]) -> list[tuple[object, ...]]:
        return sorted((tuple(r.values()) for r in records), key=repr)

    return {
        "users": rows(await pool.fetch(
            "select id, username, email, password_hash, created_at from users")),
        "sessions": rows(await pool.fetch(
            "select id, token, user_id, created_at, expires_at from sessions")),
        "entries": rows(await pool.fetch(
            "select id, user_id, sticker_id, quantity, updated_at from collection_entries")),
    }


async def _populate(pool: asyncpg.Pool) -> None:
    for name in ("alice", "bob"):
        user = await auth_service.register_user(
            pool, UserCreate(username=name, email=f"{name}@example.com", password="correct-horse-1")
        )
        await auth_service.create_session(pool, user, ttl_hours=24)
        for code, taps in {"MEX1": 3, "BRA5": 1, "ARG10": 2}.items():
            for _ in range(taps):
                await collection_service.increment_sticker(pool, user.id, code)


async def test_backup_then_restore_reproduces_everything_exactly(
    pool: asyncpg.Pool, tmp_path: Path
) -> None:
    await _populate(pool)
    before = await _snapshot(pool)
    assert before["users"] and before["sessions"] and before["entries"]

    async with pool.acquire() as conn:
        counts = await export_json(conn, tmp_path / "backup")
    assert counts == {"users": 2, "sessions": 2, "collection_entries": 6, "stickers": 992}

    # Disaster: all user data gone.
    await pool.execute("truncate users cascade")
    assert (await _snapshot(pool))["users"] == []

    # Restore with the same, already-tested import tool.
    async with pool.acquire() as conn:
        report = await import_export(conn, tmp_path / "backup", commit=True)
    assert report.committed and (report.users, report.entries) == (2, 6)

    assert await _snapshot(pool) == before  # ids, hashes, tokens, quantities, timestamps


async def test_backup_files_are_private_and_shaped_like_the_gel_export(
    pool: asyncpg.Pool, tmp_path: Path
) -> None:
    await _populate(pool)
    dest = tmp_path / "backup"

    async with pool.acquire() as conn:
        await export_json(conn, dest)

    assert stat.S_IMODE(dest.stat().st_mode) == 0o700
    for name in ("users", "sessions", "collection_entries", "stickers"):
        assert stat.S_IMODE((dest / f"{name}.json").stat().st_mode) == 0o600
    entry = json.loads((dest / "collection_entries.json").read_text())[0]
    assert set(entry) == {"id", "user", "sticker", "quantity", "updated_at"}
    assert set(entry["user"]) == {"id", "username"} and set(entry["sticker"]) == {"code"}


async def test_backing_up_an_empty_database_is_fine(pool: asyncpg.Pool, tmp_path: Path) -> None:
    async with pool.acquire() as conn:
        counts = await export_json(conn, tmp_path / "backup")

    assert counts == {"users": 0, "sessions": 0, "collection_entries": 0, "stickers": 992}
