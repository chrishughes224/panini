"""Pure view-model logic for the checklist grid.

Takes the flat, sort_order-ordered list of `StickerWithStatus` returned by
`collection_service.get_collection_for_user` and groups it into the
sections/team-blocks the template renders (Special -> Tournament -> Group
A-L, each team boxed separately -> Coca-Cola Promo).

Deliberately has no database or FastAPI dependency, so it can be unit
tested with plain in-memory fixtures.
"""

from __future__ import annotations

from app.models.checklist_view import ChecklistSection, ChecklistTeamBlock
from app.models.sticker import StickerKind, StickerWithStatus


def build_checklist_sections(
    stickers: list[StickerWithStatus],
    team_names: dict[str, str],
    team_to_group: dict[str, str],
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
            current_blocks.append(
                ChecklistTeamBlock(
                    team_code=current_team_code,
                    team_name=team_names.get(current_team_code) if current_team_code else None,
                    items=list(current_team_items),
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
