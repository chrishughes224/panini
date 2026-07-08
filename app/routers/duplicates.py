"""Duplicates router: view spare stickers and remove one when traded away."""

from __future__ import annotations

import gel
from fastapi import APIRouter, Depends, Request

from app.deps import get_db_client, require_current_user
from app.models.user import UserOut
from app.services import collection_service
from app.templating import templates

router = APIRouter(prefix="/duplicates", tags=["duplicates"])


@router.get("")
async def duplicates_index(
    request: Request,
    user: UserOut = Depends(require_current_user),
    client: gel.AsyncIOClient = Depends(get_db_client),
):
    duplicates = await collection_service.list_duplicates(client, user.id)
    return templates.TemplateResponse(
        request, "duplicates/index.html", {"user": user, "duplicates": duplicates}
    )


@router.post("/remove/{code}")
async def remove_duplicate(
    request: Request,
    code: str,
    user: UserOut = Depends(require_current_user),
    client: gel.AsyncIOClient = Depends(get_db_client),
):
    """Remove one copy of a duplicate (the user has traded it away)."""
    await collection_service.remove_one_duplicate(client, user.id, code)
    duplicates = await collection_service.list_duplicates(client, user.id)
    return templates.TemplateResponse(
        request, "duplicates/_duplicate_list.html", {"duplicates": duplicates}
    )
