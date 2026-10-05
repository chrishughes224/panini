"""Pydantic models describing how the checklist grid is grouped for display.

Kept separate from `sticker.py`/`collection.py` since these are pure
presentation structure (section/team groupings), not domain data.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.models.sticker import StickerWithStatus


class TeamProgress(BaseModel):
    """One nation's completion count - shown both in the "progress by
    country" panel and, via `ChecklistTeamBlock.progress`, in each team's
    checklist heading."""

    model_config = ConfigDict(frozen=True)

    code: str
    name: str
    iso_code: str
    collected: int
    total: int

    @property
    def percent(self) -> float:
        if self.total == 0:
            return 0.0
        return round((self.collected / self.total) * 100, 1)


class ChecklistTeamBlock(BaseModel):
    """A contiguous run of stickers for one team (or one non-team section)."""

    model_config = ConfigDict(frozen=True)

    team_code: str | None
    team_name: str | None
    items: list[StickerWithStatus]
    progress: TeamProgress | None = None


class ChecklistSection(BaseModel):
    """A top-level section of the grid: Special, Tournament, a WC group, Promo."""

    model_config = ConfigDict(frozen=True)

    title: str
    blocks: list[ChecklistTeamBlock]


class GroupProgress(BaseModel):
    """One World Cup group's teams, for the "progress by country" panel."""

    model_config = ConfigDict(frozen=True)

    letter: str
    teams: list[TeamProgress]


class HeatmapData(BaseModel):
    """The three independent sticker ownership heatmaps shown in the
    "Progress" panel's left column: Special+Tournament (exactly 20 cells),
    the 48 (teams) x 20 (sticker number) team grid (960 cells), and
    Coca-Cola Promo (12 cells, padded to 20 with `None` spacer cells so all
    three boxes share the same 20-column cell size). Each is its own box,
    stacked independently rather than one combined grid."""

    model_config = ConfigDict(frozen=True)

    special_tournament: list[bool]
    teams: list[bool]
    promo: list[bool | None]
