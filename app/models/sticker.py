"""Pydantic models (DTOs) for stickers and their per-user ownership status.

These are the strictly-typed boundary objects passed between services and
routers. `StickerKind` values intentionally match the Gel `StickerKind`
scalar enum's member names exactly, so results can be mapped 1:1.
"""

from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class StickerKind(str, Enum):
    """Mirrors the Gel `StickerKind` enum. Values match Gel member names."""

    SPECIAL = "Special"
    GENERIC = "Generic"
    PROMO = "Promo"
    TEAM = "Team"


class StickerStatus(str, Enum):
    """Derived, per-user display status for a sticker cell in the grid."""

    NOT_OWNED = "not_owned"
    OWNED = "owned"
    DUPLICATE = "duplicate"


class StickerOut(BaseModel):
    """A single canonical sticker from the catalogue (no ownership info)."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    code: str
    kind: StickerKind
    team_code: str | None
    sort_order: int


class StickerWithStatus(BaseModel):
    """A sticker combined with the current user's ownership state.

    `status` is derived from `quantity`:
      - quantity == 0 -> NOT_OWNED
      - quantity == 1 -> OWNED
      - quantity >= 2 -> DUPLICATE
    """

    model_config = ConfigDict(frozen=True)

    sticker: StickerOut
    quantity: int
    status: StickerStatus

    @classmethod
    def from_sticker_and_quantity(
        cls, sticker: StickerOut, quantity: int
    ) -> "StickerWithStatus":
        if quantity <= 0:
            status = StickerStatus.NOT_OWNED
        elif quantity == 1:
            status = StickerStatus.OWNED
        else:
            status = StickerStatus.DUPLICATE
        return cls(sticker=sticker, quantity=max(quantity, 0), status=status)
