"""Checklist router: the main sticker grid and its tap/toggle interaction.

The grid is rendered server-side. Each tap is a small HTMX request to
`/checklist/toggle/{code}` which returns just the updated cell fragment (plus
an out-of-band swap of the summary counters), so the whole page never
reloads.
"""

from __future__ import annotations

import json
from uuid import UUID

import gel
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from app.deps import get_db_client, require_current_user
from app.models.checklist_view import HeatmapData, TeamProgress
from app.models.user import UserOut
from app.services import collection_service
from app.services.catalogue_data import (
    STICKERS_PER_TEAM,
    TEAM_ISO_CODES,
    TEAM_NAMES,
    TEAM_TO_GROUP,
)
from app.services.checklist_view import (
    build_checklist_sections,
    build_group_progress,
    build_sticker_heatmap,
)
from app.templating import templates

router = APIRouter(prefix="/checklist", tags=["checklist"])


@router.get("")
async def checklist_index(
    request: Request,
    user: UserOut = Depends(require_current_user),
    client: gel.AsyncIOClient = Depends(get_db_client),
):
    stickers = await collection_service.get_collection_for_user(client, user.id)
    summary = await collection_service.get_collection_summary(client, user.id)
    sections = build_checklist_sections(stickers, TEAM_NAMES, TEAM_TO_GROUP, TEAM_ISO_CODES)
    group_progress = build_group_progress(stickers, TEAM_NAMES, TEAM_TO_GROUP, TEAM_ISO_CODES)
    heatmap = build_sticker_heatmap(stickers)
    return templates.TemplateResponse(
        request,
        "checklist/index.html",
        {
            "user": user,
            "sections": sections,
            "summary": summary,
            "group_progress": group_progress,
            "heatmap": heatmap,
        },
    )


async def _heatmap_for(client: gel.AsyncIOClient, user_id: UUID) -> HeatmapData:
    """Recompute the "Progress" panel's three heatmaps after a tap/quick-add
    - cheap enough (992 rows, local DB) to just refetch rather than patch a
    single cell client-side."""
    stickers = await collection_service.get_collection_for_user(client, user_id)
    return build_sticker_heatmap(stickers)


async def _team_progress_for(
    client: gel.AsyncIOClient, user_id: UUID, team_code: str | None
) -> TeamProgress | None:
    """Build the up-to-date progress tile for one team, or None if the
    sticker just touched isn't part of a team (e.g. "00", FWC, CC)."""
    if team_code is None:
        return None
    collected = await collection_service.count_owned_for_team(client, user_id, team_code)
    return TeamProgress(
        code=team_code,
        name=TEAM_NAMES.get(team_code, team_code),
        iso_code=TEAM_ISO_CODES.get(team_code, "").lower(),
        collected=collected,
        total=STICKERS_PER_TEAM,
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
    team_progress = await _team_progress_for(client, user.id, updated.sticker.team_code)
    heatmap = await _heatmap_for(client, user.id)

    return templates.TemplateResponse(
        request,
        "checklist/_sticker_cell.html",
        {
            "item": updated,
            "summary": summary,
            "oob_summary": True,
            "team_progress": team_progress,
            "heatmap": heatmap,
            "oob_heatmap": True,
        },
        headers={"HX-Trigger": "sticker-updated"},
    )


@router.post("/quick-add")
async def quick_add_sticker(
    request: Request,
    code: str = Form(...),
    user: UserOut = Depends(require_current_user),
    client: gel.AsyncIOClient = Depends(get_db_client),
):
    """Quick-add a sticker by typed code (e.g. from a freshly opened packet).

    Lenient on input: whitespace and casing don't matter ("mex 6" and "MEX6"
    both resolve the same way). Behaves exactly like a checklist tap -
    not-owned -> owned -> duplicate - just triggered by typing instead of
    tapping the grid. The response is entirely out-of-band (the sticker
    cell, summary bar, and team-progress tile, if visible); the caller uses
    the `quick-add-result` HX-Trigger event to show a snackbar.
    """
    normalized = "".join(code.split()).upper()

    try:
        updated = await collection_service.increment_sticker(client, user.id, normalized)
    except collection_service.StickerNotFoundError:
        return HTMLResponse(
            content="",
            headers={"HX-Trigger": json.dumps({"quick-add-result": {"ok": False, "code": normalized}})},
        )

    summary = await collection_service.get_collection_summary(client, user.id)
    team_progress = await _team_progress_for(client, user.id, updated.sticker.team_code)
    heatmap = await _heatmap_for(client, user.id)

    response = templates.TemplateResponse(
        request,
        "checklist/_sticker_cell.html",
        {
            "item": updated,
            "summary": summary,
            "oob_summary": True,
            "oob_cell": True,
            "team_progress": team_progress,
            "heatmap": heatmap,
            "oob_heatmap": True,
        },
    )
    response.headers["HX-Trigger"] = json.dumps({
        "quick-add-result": {
            "ok": True,
            "code": updated.sticker.code,
            "status": updated.status.value,
            "quantity": updated.quantity,
        }
    })
    return response


@router.post("/check")
async def check_sticker(
    code: str = Form(...),
    user: UserOut = Depends(require_current_user),
    client: gel.AsyncIOClient = Depends(get_db_client),
):
    """Look up whether a typed sticker code is already in the collection,
    without adding it - a read-only counterpart to Quick Add for checking
    while browsing in person, e.g. at a swap meet. Same lenient input
    normalization; result comes back purely via the `check-result`
    HX-Trigger event (there's nothing to swap, since nothing changed).
    """
    normalized = "".join(code.split()).upper()
    result = await collection_service.get_sticker_status(client, user.id, normalized)

    if result is None:
        detail = {"ok": False, "code": normalized}
    else:
        detail = {
            "ok": True,
            "code": result.sticker.code,
            "status": result.status.value,
        }

    return HTMLResponse(content="", headers={"HX-Trigger": json.dumps({"check-result": detail})})
