"""Back up the database to JSON files (the format `import_gel_export` restores).

    uv run python -m scripts.export_json <dest_dir>

Writes users.json, sessions.json, collection_entries.json and stickers.json,
shaped exactly like the original Gel export, so a backup can be restored into
an empty database with:

    uv run python -m scripts.import_gel_export <dest_dir> --commit

Neon's free plan only keeps ~6 hours of point-in-time history, so run this
regularly and keep the output somewhere private: the files contain password
hashes and live session tokens.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

import asyncpg

from app.config import get_settings
from app.services.db import AnyConnection


async def export_json(conn: AnyConnection, dest: Path) -> dict[str, int]:
    """Write the four JSON files into `dest`; return the row counts written."""
    dest.mkdir(parents=True, exist_ok=True)
    os.chmod(dest, 0o700)

    users = [
        {
            "id": str(r["id"]),
            "username": r["username"],
            "email": r["email"],
            "password_hash": r["password_hash"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in await conn.fetch(
            "select id, username, email, password_hash, created_at from users order by username"
        )
    ]
    sessions = [
        {
            "id": str(r["id"]),
            "token": r["token"],
            "created_at": r["created_at"].isoformat(),
            "expires_at": r["expires_at"].isoformat(),
            "user": {"id": str(r["user_id"])},
        }
        for r in await conn.fetch(
            "select id, token, user_id, created_at, expires_at from sessions order by created_at"
        )
    ]
    entries = [
        {
            "id": str(r["id"]),
            "user": {"id": str(r["user_id"]), "username": r["username"]},
            "sticker": {"code": r["code"]},
            "quantity": int(r["quantity"]),
            "updated_at": r["updated_at"].isoformat(),
        }
        for r in await conn.fetch(
            """
            select ce.id, ce.user_id, u.username, s.code, ce.quantity, ce.updated_at
            from collection_entries ce
            join users u on u.id = ce.user_id
            join stickers s on s.id = ce.sticker_id
            order by u.username, s.sort_order
            """
        )
    ]
    stickers = [
        {
            "id": str(r["id"]),
            "code": r["code"],
            "kind": r["kind"],
            "team_code": r["team_code"],
            "sort_order": r["sort_order"],
        }
        for r in await conn.fetch(
            "select id, code, kind::text as kind, team_code, sort_order from stickers order by sort_order"
        )
    ]

    files: dict[str, list[dict[str, Any]]] = {
        "users": users,
        "sessions": sessions,
        "collection_entries": entries,
        "stickers": stickers,
    }
    for name, rows in files.items():
        path = dest / f"{name}.json"
        path.write_text(json.dumps(rows), encoding="utf-8")
        os.chmod(path, 0o600)
    return {name: len(rows) for name, rows in files.items()}


async def _main(dest: Path) -> None:
    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is not set.")
    conn = await asyncpg.connect(settings.database_url, statement_cache_size=0)
    try:
        counts = await export_json(conn, dest)
    finally:
        await conn.close()
    print(f"Backed up to {dest}: " + ", ".join(f"{n} {name}" for name, n in counts.items()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dest_dir", type=Path)
    args = parser.parse_args()
    asyncio.run(_main(args.dest_dir))


if __name__ == "__main__":
    main()
