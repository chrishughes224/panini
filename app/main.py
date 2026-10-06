"""FastAPI application entry point.

Run with:
    uv run uvicorn app.main:app --host 0.0.0.0 --port 8003

Requires DATABASE_URL (Postgres) in .env or the environment.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.deps import get_current_user
from app.models.user import UserOut
from app.routers import auth, checklist, duplicates, export
from app.services.db import close_pool

STATIC_DIR = Path(__file__).parent.parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await close_pool()


app = FastAPI(title="Panini FIFA World Cup 2026 Sticker Tracker", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(auth.router)
app.include_router(checklist.router)
app.include_router(duplicates.router)
app.include_router(export.router)


@app.get("/")
async def root(user: UserOut | None = Depends(get_current_user)) -> RedirectResponse:
    """Redirect to the checklist if logged in, otherwise to login."""
    if user is not None:
        return RedirectResponse(url="/checklist")
    return RedirectResponse(url="/login")
