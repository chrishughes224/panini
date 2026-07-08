"""Pydantic models describing how the checklist grid is grouped for display.

Kept separate from `sticker.py`/`collection.py` since these are pure
presentation structure (section/team groupings), not domain data.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.models.sticker import StickerWithStatus


class ChecklistTeamBlock(BaseModel):
    """A contiguous run of stickers for one team (or one non-team section)."""

    model_config = ConfigDict(frozen=True)

    team_code: str | None
    team_name: str | None
    items: list[StickerWithStatus]


class ChecklistSection(BaseModel):
    """A top-level section of the grid: Special, Tournament, a WC group, Promo."""

    model_config = ConfigDict(frozen=True)

    title: str
    blocks: list[ChecklistTeamBlock]
