"""Pydantic models (DTOs) for the user's overall collection state."""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict

PACK_SIZE = 7


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

    @property
    def min_packs_required(self) -> int:
        """Fewest packs (7 stickers each) that could possibly fill every
        remaining gap, assuming maximally lucky pulls (no further
        duplicates)."""
        still_needed = self.total_stickers - self.total_collected
        return math.ceil(still_needed / PACK_SIZE)

    @property
    def spare_packs(self) -> int:
        """Roughly how many whole packs' worth of stickers are sitting
        around as spares, rounded down."""
        return self.total_duplicates // PACK_SIZE

    @property
    def spare_packs_caption(self) -> str | None:
        """"That's about N pack(s)" caption, or None when there isn't even
        one whole pack's worth of spares to mention."""
        packs = self.spare_packs
        if packs == 0:
            return None
        noun = "pack" if packs == 1 else "packs"
        return f"That's about {packs} {noun}"
