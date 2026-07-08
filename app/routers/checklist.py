"""Checklist router: the main sticker grid and its tap/toggle interaction.

The grid is rendered server-side. Each tap is a small HTMX request to
`/checklist/toggle/{code}` which returns just the updated cell fragment (plus
an out-of-band swap of the summary counters), so the whole page never
reloads.
"""

from __future__ import annotations

import gel
from fastapi import APIRouter, Depends, Form, Request

from app.deps import get_db_client, require_current_user
from app.models.user import UserOut
from app.services import collection_service
from app.services.catalogue_data import TEAM_TO_GROUP
from app.services.checklist_view import build_checklist_sections
from app.templating import templates

router = APIRouter(prefix="/checklist", tags=["checklist"])

TEAM_NAMES: dict[str, str] = {
    "MEX": "Mexico", "RSA": "South Africa", "KOR": "South Korea", "CZE": "Czech Republic",
    "CAN": "Canada", "BIH": "Bosnia & Herzegovina", "QAT": "Qatar", "SUI": "Switzerland",
    "BRA": "Brazil", "MAR": "Morocco", "HAI": "Haiti", "SCO": "Scotland",
    "USA": "United States", "PAR": "Paraguay", "AUS": "Australia", "TUR": "Turkey",
    "GER": "Germany", "CUW": "Curaçao", "CIV": "Ivory Coast", "ECU": "Ecuador",
    "NED": "Netherlands", "JPN": "Japan", "SWE": "Sweden", "TUN": "Tunisia",
    "BEL": "Belgium", "EGY": "Egypt", "IRN": "Iran", "NZL": "New Zealand",
    "ESP": "Spain", "CPV": "Cape Verde", "KSA": "Saudi Arabia", "URU": "Uruguay",
    "FRA": "France", "SEN": "Senegal", "IRQ": "Iraq", "NOR": "Norway",
    "ARG": "Argentina", "ALG": "Algeria", "AUT": "Austria", "JOR": "Jordan",
    "POR": "Portugal", "COD": "DR Congo", "UZB": "Uzbekistan", "COL": "Colombia",
    "ENG": "England", "CRO": "Croatia", "GHA": "Ghana", "PAN": "Panama",
}


@router.get("")
async def checklist_index(
    request: Request,
    user: UserOut = Depends(require_current_user),
    client: gel.AsyncIOClient = Depends(get_db_client),
):
    stickers = await collection_service.get_collection_for_user(client, user.id)
    summary = await collection_service.get_collection_summary(client, user.id)
    sections = build_checklist_sections(stickers, TEAM_NAMES, TEAM_TO_GROUP)
    return templates.TemplateResponse(
        request,
        "checklist/index.html",
        {
            "user": user,
            "sections": sections,
            "summary": summary,
        },
    )


@router.post("/toggle/{code}")
async def toggle_sticker(
    request: Request,
    code: str,
    edit_mode: bool = Form(False),
    user: UserOut = Depends(require_current_user),
    client: gel.AsyncIOClient = Depends(get_db_client),
):
    """Handle a single tap on one sticker cell.

    `edit_mode=true` (sent by the client when the Edit-mode toggle is on)
    decrements/undoes instead of the normal increment.
    """
    if edit_mode:
        updated = await collection_service.decrement_sticker(client, user.id, code)
    else:
        updated = await collection_service.increment_sticker(client, user.id, code)

    summary = await collection_service.get_collection_summary(client, user.id)

    return templates.TemplateResponse(
        request,
        "checklist/_sticker_cell.html",
        {"item": updated, "summary": summary, "oob_summary": True},
        headers={"HX-Trigger": "sticker-updated"},
    )
