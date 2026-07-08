"""Pydantic models (DTOs) for the user's overall collection state."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.models.sticker import StickerOut


class CollectionSummary(BaseModel):
    """Aggregate progress counters shown on the checklist page header."""

    model_config = ConfigDict(frozen=True)

    total_stickers: int
    total_collected: int
    total_duplicates: int

    @property
    def percent_complete(self) -> float:
        if self.total_stickers == 0:
            return 0.0
        return round((self.total_collected / self.total_stickers) * 100, 1)


class DuplicateEntry(BaseModel):
    """A single row in the duplicates view: a sticker owned more than once."""

    model_config = ConfigDict(frozen=True)

    sticker: StickerOut
    quantity: int
