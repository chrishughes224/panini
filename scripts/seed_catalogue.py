"""One-off script to populate the canonical 992-sticker catalogue.

Run with:
    uv run python scripts/seed_catalogue.py

Idempotent: existing stickers are matched by their exclusive `code` and only
have `sort_order` refreshed, so this is safe to re-run (e.g. after tweaking
`catalogue_data.py`) without creating duplicate rows.
"""

from __future__ import annotations

import asyncio
import json

from app.services.catalogue_data import build_catalogue, expected_total_stickers
from app.services.db import get_client

_SEED_QUERY = """
with data := <json>$data
for item in json_array_unpack(data) union (
    insert Sticker {
        code := <str>item['code'],
        kind := <StickerKind><str>item['kind'],
        team_code := (
            <str>item['team_code'] if <str>item['team_code'] != '' else <str>{}
        ),
        sort_order := <int32>item['sort_order'],
    }
    unless conflict on (.code)
    else (
        update Sticker
        set { sort_order := <int32>item['sort_order'] }
    )
)
"""


async def seed() -> None:
    client = get_client()
    rows = build_catalogue()
    payload = json.dumps(
        [
            {
                "code": row.code,
                "kind": row.kind.value,
                "team_code": row.team_code or "",
                "sort_order": row.sort_order,
            }
            for row in rows
        ]
    )

    await client.query(_SEED_QUERY, data=payload)

    total = await client.query_single("select count(Sticker)")
    expected = expected_total_stickers()
    print(f"Seeded catalogue: {total} stickers in DB (expected {expected}).")
    if total != expected:
        raise SystemExit(f"Mismatch! Expected {expected} stickers but found {total}.")

    await client.aclose()


if __name__ == "__main__":
    asyncio.run(seed())
