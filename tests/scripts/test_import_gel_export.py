from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import asyncpg
import pytest

from scripts.import_gel_export import ImportAbortedError, import_export

U1 = "11111111-1111-1111-1111-111111111111"
U2 = "22222222-2222-2222-2222-222222222222"


async def _write_export(pool: asyncpg.Pool, dest: Path, *, bad_code: bool = False) -> None:
    """A tiny export in the same shape `gel query --output-format=json` produced."""
    stickers = [
        {"id": str(r["id"]), "code": r["code"], "kind": r["kind"], "team_code": r["team_code"],
         "sort_order": r["sort_order"]}
        for r in await pool.fetch(
            "select id, code, kind::text as kind, team_code, sort_order from stickers order by sort_order"
        )
    ]
    users = [
        {"id": U1, "username": "Chris", "email": "c@example.com",
         "password_hash": "$argon2id$v=19$hash-one", "created_at": "2026-07-08T10:56:21.59801+00:00"},
        {"id": U2, "username": "bob", "email": "o@example.com",
         "password_hash": "$argon2id$v=19$hash-two", "created_at": "2026-07-09T08:00:00.123456+00:00"},
    ]
    sessions = [
        {"id": "33333333-3333-3333-3333-333333333333", "token": "tok-abc",
         "created_at": "2026-07-08T11:03:34.534761+00:00", "expires_at": "2099-01-01T00:00:00+00:00",
         "user": {"id": U1, "username": "Chris"}},
    ]
    entries: list[dict[str, Any]] = [
        {"id": "44444444-4444-4444-4444-444444444441", "user": {"id": U1, "username": "Chris"},
         "sticker": {"code": "MEX1"}, "quantity": 1, "updated_at": "2026-08-26T10:54:38.187224+00:00"},
        {"id": "44444444-4444-4444-4444-444444444442", "user": {"id": U1, "username": "Chris"},
         "sticker": {"code": "BRA5"}, "quantity": 3, "updated_at": "2026-08-27T09:00:00+00:00"},
        {"id": "44444444-4444-4444-4444-444444444443", "user": {"id": U2, "username": "bob"},
         "sticker": {"code": "ZZZ99" if bad_code else "KOR8"}, "quantity": 2,
         "updated_at": "2026-08-28T12:30:00.5+00:00"},
    ]
    for name, data in (("stickers", stickers), ("users", users), ("sessions", sessions),
                       ("collection_entries", entries)):
        (dest / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


async def _counts(pool: asyncpg.Pool) -> tuple[int, int, int]:
    return (
        await pool.fetchval("select count(*) from users"),
        await pool.fetchval("select count(*) from sessions"),
        await pool.fetchval("select count(*) from collection_entries"),
    )


async def test_commit_imports_everything_exactly(pool: asyncpg.Pool, tmp_path: Path) -> None:
    await _write_export(pool, tmp_path)

    async with pool.acquire() as conn:
        report = await import_export(conn, tmp_path, commit=True)

    assert (report.users, report.sessions, report.entries, report.committed) == (2, 1, 3, True)
    assert await _counts(pool) == (2, 1, 3)

    # Ids, hashes, tokens and timestamps survive untouched.
    row = await pool.fetchrow("select * from users where username = 'Chris'")
    assert row is not None
    assert str(row["id"]) == U1
    assert row["password_hash"] == "$argon2id$v=19$hash-one"
    assert row["created_at"].isoformat() == "2026-07-08T10:56:21.598010+00:00"
    assert await pool.fetchval("select user_id::text from sessions where token = 'tok-abc'") == U1
    assert await pool.fetchval(
        "select ce.quantity from collection_entries ce join stickers s on s.id = ce.sticker_id "
        "where s.code = 'BRA5'"
    ) == 3


async def test_imported_session_still_logs_the_user_in(pool: asyncpg.Pool, tmp_path: Path) -> None:
    from app.services import auth_service

    await _write_export(pool, tmp_path)
    async with pool.acquire() as conn:
        await import_export(conn, tmp_path, commit=True)

    user = await auth_service.get_user_by_session_token(pool, "tok-abc")

    assert user is not None and user.username == "Chris"


async def test_dry_run_writes_nothing(pool: asyncpg.Pool, tmp_path: Path) -> None:
    await _write_export(pool, tmp_path)

    async with pool.acquire() as conn:
        report = await import_export(conn, tmp_path, commit=False)

    assert report.committed is False and report.users == 2
    assert await _counts(pool) == (0, 0, 0)


async def test_unknown_sticker_aborts_and_rolls_back(pool: asyncpg.Pool, tmp_path: Path) -> None:
    await _write_export(pool, tmp_path, bad_code=True)

    async with pool.acquire() as conn:
        with pytest.raises(ImportAbortedError, match="unknown sticker"):
            await import_export(conn, tmp_path, commit=True)

    assert await _counts(pool) == (0, 0, 0)


async def test_refuses_a_database_that_already_has_users(pool: asyncpg.Pool, tmp_path: Path) -> None:
    await _write_export(pool, tmp_path)
    await pool.execute(
        "insert into users (username, email, password_hash) values ('existing', 'e@example.com', 'x')"
    )

    async with pool.acquire() as conn:
        with pytest.raises(ImportAbortedError, match="already contains users"):
            await import_export(conn, tmp_path, commit=True)

    assert await _counts(pool) == (1, 0, 0)  # untouched


async def test_catalogue_mismatch_aborts(pool: asyncpg.Pool, tmp_path: Path) -> None:
    await _write_export(pool, tmp_path)
    stickers = json.loads((tmp_path / "stickers.json").read_text())
    stickers[5]["sort_order"] += 1000
    (tmp_path / "stickers.json").write_text(json.dumps(stickers))

    async with pool.acquire() as conn:
        with pytest.raises(ImportAbortedError, match="catalogue does not match"):
            await import_export(conn, tmp_path, commit=True)

    assert await _counts(pool) == (0, 0, 0)
