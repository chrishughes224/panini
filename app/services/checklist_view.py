"""Pure view-model logic for the checklist grid.

Takes the flat, sort_order-ordered list of `StickerWithStatus` returned by
`collection_service.get_collection_for_user` and groups it into the
sections/team-blocks the template renders (Special -> Tournament -> Group
A-L, each team boxed separately -> Coca-Cola Promo).

Deliberately has no database or FastAPI dependency, so it can be unit
tested with plain in-memory fixtures.
"""

from __future__ import annotations

from app.models.checklist_view import (
    ChecklistSection,
    ChecklistTeamBlock,
    GroupProgress,
    HeatmapData,
    TeamProgress,
)
from app.models.sticker import StickerKind, StickerStatus, StickerWithStatus


def build_checklist_sections(
    stickers: list[StickerWithStatus],
    team_names: dict[str, str],
    team_to_group: dict[str, str],
    team_iso_codes: dict[str, str],
) -> list[ChecklistSection]:
    """Group an ordered sticker list into display sections.

    Relies on `stickers` already being ordered by `sort_order` (as
    `collection_service.get_collection_for_user` guarantees), so a single
    pass with boundary detection is sufficient.
    """
    sections: list[ChecklistSection] = []

    current_section_key: str | None = None
    current_blocks: list[ChecklistTeamBlock] = []
    current_team_code: str | None = None
    current_team_items: list[StickerWithStatus] = []

    def flush_team_block() -> None:
        if current_team_items:
            progress = None
            if current_team_code is not None:
                collected = sum(
                    1 for item in current_team_items if item.status != StickerStatus.NOT_OWNED
                )
                progress = TeamProgress(
                    code=current_team_code,
                    name=team_names.get(current_team_code, current_team_code),
                    iso_code=team_iso_codes.get(current_team_code, "").lower(),
                    collected=collected,
                    total=len(current_team_items),
                )
            current_blocks.append(
                ChecklistTeamBlock(
                    team_code=current_team_code,
                    team_name=team_names.get(current_team_code) if current_team_code else None,
                    items=list(current_team_items),
                    progress=progress,
                )
            )
            current_team_items.clear()

    def flush_section(title: str) -> None:
        flush_team_block()
        if current_blocks:
            sections.append(ChecklistSection(title=title, blocks=list(current_blocks)))
            current_blocks.clear()

    section_titles: dict[str, str] = {}

    for item in stickers:
        kind = item.sticker.kind
        team_code = item.sticker.team_code

        if kind == StickerKind.SPECIAL:
            section_key = "special"
            title = "Special"
        elif kind == StickerKind.GENERIC:
            section_key = "generic"
            title = "Tournament"
        elif kind == StickerKind.PROMO:
            section_key = "promo"
            title = "Coca-Cola Promo"
        else:  # StickerKind.TEAM
            group_letter = team_to_group.get(team_code or "", "?")
            section_key = f"group-{group_letter}"
            title = f"Group {group_letter}"

        if section_key != current_section_key:
            if current_section_key is not None:
                flush_section(section_titles[current_section_key])
            current_section_key = section_key
            section_titles[section_key] = title
            current_team_code = None

        if team_code != current_team_code:
            flush_team_block()
            current_team_code = team_code

        current_team_items.append(item)

    if current_section_key is not None:
        flush_section(section_titles[current_section_key])

    return sections


def build_group_progress(
    stickers: list[StickerWithStatus],
    team_names: dict[str, str],
    team_to_group: dict[str, str],
    team_iso_codes: dict[str, str],
) -> list[GroupProgress]:
    """Per-team completion counts, grouped by World Cup group A-L.

    Only TEAM-kind stickers count; each team's `total` is derived from how
    many of its stickers actually appear (rather than a hardcoded 20), so
    this stays correct even if the catalogue ever changes.
    """
    collected_by_team: dict[str, int] = {}
    total_by_team: dict[str, int] = {}

    for item in stickers:
        team_code = item.sticker.team_code
        if item.sticker.kind != StickerKind.TEAM or team_code is None:
            continue
        total_by_team[team_code] = total_by_team.get(team_code, 0) + 1
        if item.status != StickerStatus.NOT_OWNED:
            collected_by_team[team_code] = collected_by_team.get(team_code, 0) + 1

    groups: dict[str, list[TeamProgress]] = {}
    for team_code, total in total_by_team.items():
        group_letter = team_to_group.get(team_code, "?")
        groups.setdefault(group_letter, []).append(
            TeamProgress(
                code=team_code,
                name=team_names.get(team_code, team_code),
                iso_code=team_iso_codes.get(team_code, "").lower(),
                collected=collected_by_team.get(team_code, 0),
                total=total,
            )
        )

    return [GroupProgress(letter=letter, teams=groups[letter]) for letter in sorted(groups)]


def build_team_ownership_grid(stickers: list[StickerWithStatus]) -> list[bool]:
    """A 48 (teams, catalogue order) x 20 (sticker number) ownership grid
    for the summary bar's compact heatmap, flattened row-major *by team*
    (all 48 of team #1's stickers 1-20, then all of team #2's, ...) so it
    can be dropped straight into a `grid-template-columns: repeat(20, ...)`
    CSS grid and read left-to-right (sticker 1-20 within a team), top-to-
    bottom (team by team) without any client-side reshuffling.
    """
    by_team: dict[str, dict[int, bool]] = {}
    for item in stickers:
        team_code = item.sticker.team_code
        if item.sticker.kind != StickerKind.TEAM or team_code is None:
            continue
        number = int(item.sticker.code[len(team_code):])
        by_team.setdefault(team_code, {})[number] = item.status != StickerStatus.NOT_OWNED

    team_codes = list(by_team.keys())  # first-seen = catalogue order
    return [
        by_team[team_code].get(number, False)
        for team_code in team_codes
        for number in range(1, 21)
    ]


def build_sticker_heatmap(stickers: list[StickerWithStatus]) -> HeatmapData:
    """The three independent heatmaps for the "Progress" panel: Special
    ("00") + Tournament (FWC1-19) - exactly 20, needs no padding - the 48
    (teams) x 20 (sticker number) team grid, and Coca-Cola Promo (12,
    padded to 20 with `None` spacer cells so all three boxes share the same
    20-column cell size even though they're rendered as separate boxes of
    differing height).
    """
    GRID_WIDTH = 20

    special_tournament: list[bool] = [
        item.status != StickerStatus.NOT_OWNED
        for item in stickers
        if item.sticker.kind in (StickerKind.SPECIAL, StickerKind.GENERIC)
    ]
    promo: list[bool | None] = [
        item.status != StickerStatus.NOT_OWNED
        for item in stickers
        if item.sticker.kind == StickerKind.PROMO
    ]
    promo += [None] * (GRID_WIDTH - len(promo))

    return HeatmapData(
        special_tournament=special_tournament,
        teams=build_team_ownership_grid(stickers),
        promo=promo,
    )
