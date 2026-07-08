"""Service layer for reading the sticker catalogue.

Services contain business logic and talk to Gel directly. They know nothing
about HTTP, `Request`/`Response`, or Jinja - routers are responsible for that
translation. Every function here takes an already-obtained Gel client
(injected by the router via a FastAPI dependency) so it stays trivially
testable against a real test database.
"""

from __future__ import annotations

import gel

from app.models.sticker import StickerKind, StickerOut


async def list_all_stickers(client: gel.AsyncIOClient) -> list[StickerOut]:
    """Return the full sticker catalogue, ordered for grid display."""
    result = await client.query(
        """
        select Sticker {
            id, code, kind, team_code, sort_order
        }
        order by .sort_order
        """
    )
    return [
        StickerOut(
            id=row.id,
            code=row.code,
            kind=StickerKind(row.kind),
            team_code=row.team_code,
            sort_order=row.sort_order,
        )
        for row in result
    ]


async def get_sticker_by_code(client: gel.AsyncIOClient, code: str) -> StickerOut | None:
    """Look up a single sticker by its code (e.g. "MEX7", "FWC3", "00")."""
    row = await client.query_single(
        """
        select Sticker {
            id, code, kind, team_code, sort_order
        }
        filter .code = <str>$code
        """,
        code=code,
    )
    if row is None:
        return None
    return StickerOut(
        id=row.id,
        code=row.code,
        kind=StickerKind(row.kind),
        team_code=row.team_code,
        sort_order=row.sort_order,
    )


async def count_all_stickers(client: gel.AsyncIOClient) -> int:
    """Total number of stickers in the catalogue (expected: 992)."""
    return await client.query_single("select count(Sticker)")
