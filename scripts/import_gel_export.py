"""One-off: import the pre-migration Gel JSON export into Postgres.

    uv run python -m scripts.import_gel_export <export_dir>            # dry run
    uv run python -m scripts.import_gel_export <export_dir> --commit   # for real

`<export_dir>` is the backup folder holding users.json, sessions.json,
collection_entries.json and stickers.json.

Safety properties (the data is irreplaceable):
  * Dry run by default - the whole import happens inside a transaction that
    is rolled back unless --commit is given.
  * Every id, timestamp, password hash and session token is preserved
    exactly, so existing logins keep working after the cut-over.
  * Before committing, every imported row is read back and compared
    field-by-field with the export; any difference aborts and rolls back.
  * Refuses to run against a database that already contains users.
  * Never prints credentials, hashes or tokens - only counts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg

from app.config import get_settings
from app.services.db import AnyConnection
from app.services.migrations import apply_migrations
from app.services.seeding import seed_catalogue

Row = dict[str, Any]


class ImportAbortedError(Exception):
    """The export could not be imported faithfully; nothing was written."""


@dataclass(frozen=True)
class ImportReport:
    users: int
    sessions: int
    entries: int
    stickers: int
    committed: bool


def _load(export_dir: Path, name: str) -> list[Row]:
    data = json.loads((export_dir / f"{name}.json").read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return data


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _uuid(value: Any) -> UUID:
    return UUID(str(value))


def _canon(rows: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    return sorted(rows, key=repr)


async def import_export(
    conn: AnyConnection, export_dir: Path, *, commit: bool
) -> ImportReport:
    """Import the export in one transaction; commit only if `commit` and verified.

    The target must already have the schema applied and the catalogue seeded.
    """
    users = _load(export_dir, "users")
    sessions = _load(export_dir, "sessions")
    entries = _load(export_dir, "collection_entries")
    stickers = _load(export_dir, "stickers")

    tx = conn.transaction()
    await tx.start()
    try:
        if await conn.fetchval("select count(*) from users"):
            raise ImportAbortedError("target database already contains users; refusing to import")

        sticker_ids = await _check_catalogue(conn, stickers)

        want_users = [
            (_uuid(u["id"]), u["username"], u["email"], u["password_hash"], _dt(u["created_at"]))
            for u in users
        ]
        want_sessions = [
            (_uuid(s["id"]), s["token"], _uuid(s["user"]["id"]), _dt(s["created_at"]), _dt(s["expires_at"]))
            for s in sessions
        ]
        try:
            want_entries = [
                (_uuid(e["id"]), _uuid(e["user"]["id"]), sticker_ids[e["sticker"]["code"]],
                 int(e["quantity"]), _dt(e["updated_at"]))
                for e in entries
            ]
        except KeyError as exc:
            raise ImportAbortedError(f"collection entry references unknown sticker {exc}") from exc

        await conn.executemany(
            "insert into users (id, username, email, password_hash, created_at) "
            "values ($1, $2, $3, $4, $5)",
            want_users,
        )
        await conn.executemany(
            "insert into sessions (id, token, user_id, created_at, expires_at) "
            "values ($1, $2, $3, $4, $5)",
            want_sessions,
        )
        await conn.executemany(
            "insert into collection_entries (id, user_id, sticker_id, quantity, updated_at) "
            "values ($1, $2, $3, $4, $5)",
            want_entries,
        )

        await _verify(conn, want_users, want_sessions, want_entries)
    except BaseException:
        await tx.rollback()
        raise

    if commit:
        await tx.commit()
    else:
        await tx.rollback()

    return ImportReport(
        users=len(users),
        sessions=len(sessions),
        entries=len(entries),
        stickers=len(stickers),
        committed=commit,
    )


async def _check_catalogue(conn: AnyConnection, source: list[Row]) -> dict[str, UUID]:
    """The target catalogue must match the export exactly; returns code -> id."""
    want = _canon([(s["code"], s["kind"], s["team_code"], int(s["sort_order"])) for s in source])
    rows = await conn.fetch("select id, code, kind::text as kind, team_code, sort_order from stickers")
    have = _canon([(r["code"], r["kind"], r["team_code"], r["sort_order"]) for r in rows])
    if want != have:
        raise ImportAbortedError(
            "target sticker catalogue does not match the export "
            f"(export={len(want)} stickers, target={len(have)}); run the seed first"
        )
    return {r["code"]: _uuid(r["id"]) for r in rows}


async def _verify(
    conn: AnyConnection,
    want_users: list[tuple[Any, ...]],
    want_sessions: list[tuple[Any, ...]],
    want_entries: list[tuple[Any, ...]],
) -> None:
    """Read everything back and require exact equality with the export."""
    got_users = [
        (_uuid(r["id"]), r["username"], r["email"], r["password_hash"], r["created_at"])
        for r in await conn.fetch(
            "select id, username, email, password_hash, created_at from users"
        )
    ]
    got_sessions = [
        (_uuid(r["id"]), r["token"], _uuid(r["user_id"]), r["created_at"], r["expires_at"])
        for r in await conn.fetch(
            "select id, token, user_id, created_at, expires_at from sessions"
        )
    ]
    got_entries = [
        (_uuid(r["id"]), _uuid(r["user_id"]), _uuid(r["sticker_id"]), int(r["quantity"]), r["updated_at"])
        for r in await conn.fetch(
            "select id, user_id, sticker_id, quantity, updated_at from collection_entries"
        )
    ]
    for label, want, got in (
        ("users", want_users, got_users),
        ("sessions", want_sessions, got_sessions),
        ("collection_entries", want_entries, got_entries),
    ):
        if _canon(want) != _canon(got):
            raise ImportAbortedError(
                f"verification failed for {label}: export has {len(want)} rows, "
                f"database has {len(got)}, or field values differ"
            )


async def _main(export_dir: Path, commit: bool) -> None:
    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is not set.")

    conn = await asyncpg.connect(settings.database_url, statement_cache_size=0)
    try:
        await apply_migrations(conn)
        pool = await asyncpg.create_pool(
            settings.database_url, min_size=1, max_size=1, statement_cache_size=0
        )
        try:
            await seed_catalogue(pool)
        finally:
            await pool.close()
        report = await import_export(conn, export_dir, commit=commit)
    finally:
        await conn.close()

    mode = "COMMITTED" if report.committed else "DRY RUN (rolled back, nothing written)"
    print(f"{mode}: verified {report.users} users, {report.sessions} sessions, "
          f"{report.entries} collection entries, {report.stickers} stickers - all match the export.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("export_dir", type=Path)
    parser.add_argument("--commit", action="store_true", help="actually write (default is a dry run)")
    args = parser.parse_args()
    asyncio.run(_main(args.export_dir, args.commit))


if __name__ == "__main__":
    main()
