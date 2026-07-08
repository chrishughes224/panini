"""Export router: plain-text 'needs' and 'swaps' lists for copy/paste, plus
the structured team-row data the client-side canvas renderer turns into a
shareable image.

Each endpoint returns the dialog fragment swapped into the persistent
`#export-dialog` in `base.html`; the triggering button then opens it via
`hx-on::after-request`.
"""

from __future__ import annotations

import json
from dataclasses import asdict

import gel
from fastapi import APIRouter, Depends, Request

from app.deps import get_db_client, require_current_user
from app.models.user import UserOut
from app.services import collection_service, export_service
from app.templating import templates

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/needs")
async def export_needs(
    request: Request,
    user: UserOut = Depends(require_current_user),
    client: gel.AsyncIOClient = Depends(get_db_client),
):
    stickers = await collection_service.get_collection_for_user(client, user.id)
    text = export_service.build_needs_list(stickers)
    rows = export_service.build_needs_rows(stickers)
    return templates.TemplateResponse(
        request,
        "export/_dialog.html",
        {
            "title": "Needs",
            "empty_message": "You already have everything!",
            "text": text,
            "rows_json": json.dumps([asdict(row) for row in rows]),
        },
    )


@router.get("/swaps")
async def export_swaps(
    request: Request,
    user: UserOut = Depends(require_current_user),
    client: gel.AsyncIOClient = Depends(get_db_client),
):
    stickers = await collection_service.get_collection_for_user(client, user.id)
    text = export_service.build_swaps_list(stickers)
    rows = export_service.build_swaps_rows(stickers)
    return templates.TemplateResponse(
        request,
        "export/_dialog.html",
        {
            "title": "Swaps",
            "empty_message": "No duplicates right now.",
            "text": text,
            "rows_json": json.dumps([asdict(row) for row in rows]),
        },
    )
