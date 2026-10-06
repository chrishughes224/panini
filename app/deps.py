"""Shared FastAPI dependencies: DB pool access and current-user resolution.

Routers depend on `get_current_user` (or `require_current_user`) rather than
touching sessions/cookies directly, keeping that concern in one place.
"""

from __future__ import annotations

import asyncpg
from fastapi import Depends, HTTPException, Request, status

from app.config import Settings, get_settings
from app.models.user import UserOut
from app.services import auth_service
from app.services.db import get_pool


async def get_db_client() -> asyncpg.Pool:
    """FastAPI dependency yielding the shared asyncpg pool.

    (Name kept from the Gel era so routers and test overrides are unchanged.)
    """
    return await get_pool()


async def get_current_user(
    request: Request,
    settings: Settings = Depends(get_settings),
    client: asyncpg.Pool = Depends(get_db_client),
) -> UserOut | None:
    """Resolve the logged-in user from the session cookie, or None."""
    token = request.cookies.get(settings.session_cookie_name)
    if token is None:
        return None
    return await auth_service.get_user_by_session_token(client, token)


async def require_current_user(
    user: UserOut | None = Depends(get_current_user),
) -> UserOut:
    """Like `get_current_user`, but raises 401 if nobody is logged in.

    Protected routers depend on this instead of `get_current_user` directly.
    """
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated"
        )
    return user
