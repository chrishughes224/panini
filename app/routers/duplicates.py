"""Duplicates router: a checklist-style grid of just the spare stickers,
grouped into the same sections/team-blocks as the main checklist (but only
the sections/teams that actually have a duplicate)."""

from __future__ import annotations

import json
from uuid import UUID

import gel
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from app.deps import get_db_client, require_current_user
from app.models.checklist_view import ChecklistSection
from app.models.sticker import StickerStatus
from app.models.user import UserOut
from app.services import collection_service
from app.services.catalogue_data import TEAM_ISO_CODES, TEAM_NAMES, TEAM_TO_GROUP
from app.services.checklist_view import build_checklist_sections
from app.templating import templates

router = APIRouter(prefix="/duplicates", tags=["duplicates"])


async def _build_duplicate_sections(client: gel.AsyncIOClient, user_id: UUID) -> list[ChecklistSection]:
    """Same section/team grouping as the checklist grid, but pre-filtered
    to only duplicate-owned stickers - sections and team blocks with no
    duplicates simply never appear, since `build_checklist_sections` only
    emits a block/section when it has at least one item."""
    stickers = await collection_service.get_collection_for_user(client, user_id)
    duplicates = [item for item in stickers if item.status == StickerStatus.DUPLICATE]
    return build_checklist_sections(duplicates, TEAM_NAMES, TEAM_TO_GROUP, TEAM_ISO_CODES)


@router.get("")
async def duplicates_index(
    request: Request,
    user: UserOut = Depends(require_current_user),
    client: gel.AsyncIOClient = Depends(get_db_client),
):
    sections = await _build_duplicate_sections(client, user.id)
    return templates.TemplateResponse(
        request, "duplicates/index.html", {"user": user, "sections": sections}
    )


@router.post("/remove/{code}")
async def remove_duplicate(
    request: Request,
    code: str,
    user: UserOut = Depends(require_current_user),
    client: gel.AsyncIOClient = Depends(get_db_client),
):
    """Remove one copy of a duplicate (the user has traded it away).

    Triggered by tapping a sticker cell directly in the grid, which targets
    and replaces `#duplicate-list` wholesale - simplest way to correctly
    handle a whole team/section heading disappearing once its last
    duplicate is gone.
    """
    await collection_service.remove_one_duplicate(client, user.id, code)
    sections = await _build_duplicate_sections(client, user.id)
    return templates.TemplateResponse(
        request, "duplicates/_duplicate_list.html", {"sections": sections}
    )


@router.post("/trade-away")
async def trade_away_sticker(
    request: Request,
    code: str = Form(...),
    user: UserOut = Depends(require_current_user),
    client: gel.AsyncIOClient = Depends(get_db_client),
):
    """Trade away one spare by typed code, from the floating Trade Away
    button - a low-friction alternative to finding the sticker's cell in
    the grid. Same lenient input normalization as Quick Add/Check. Only
    acts if the sticker is actually a current duplicate (quantity >= 2);
    the result comes back via the `trade-away-result` HX-Trigger event, and
    the grid is refreshed out-of-band when a trade actually happens.
    """
    normalized = "".join(code.split()).upper()
    current = await collection_service.get_sticker_status(client, user.id, normalized)

    if current is None:
        detail = {"ok": False, "reason": "unknown", "code": normalized}
        return HTMLResponse(content="", headers={"HX-Trigger": json.dumps({"trade-away-result": detail})})

    if current.status != StickerStatus.DUPLICATE:
        detail = {"ok": False, "reason": "no_spare", "code": normalized}
        return HTMLResponse(content="", headers={"HX-Trigger": json.dumps({"trade-away-result": detail})})

    await collection_service.remove_one_duplicate(client, user.id, normalized)
    sections = await _build_duplicate_sections(client, user.id)

    response = templates.TemplateResponse(
        request,
        "duplicates/_duplicate_list.html",
        {"sections": sections, "oob": True},
    )
    response.headers["HX-Trigger"] = json.dumps(
        {"trade-away-result": {"ok": True, "code": normalized}}
    )
    return response
