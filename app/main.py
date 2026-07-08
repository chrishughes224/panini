"""FastAPI application entry point.

Run with:
    uv run uvicorn app.main:app --host 192.168.1.170 --port 8003
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.deps import get_current_user
from app.models.user import UserOut
from app.routers import auth, checklist, duplicates, export

STATIC_DIR = Path(__file__).parent.parent / "static"

app = FastAPI(title="Panini FIFA World Cup 2026 Sticker Tracker")

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
