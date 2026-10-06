"""Auth router: registration, login, logout.

Renders full pages (not HTMX fragments) since these are entry/exit points to
the app rather than in-page interactions.
"""

from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.deps import get_db_client, get_current_user
from app.models.user import LoginRequest, UserCreate, UserOut
from app.services import auth_service
from app.templating import templates

router = APIRouter(tags=["auth"])


@router.get("/login")
async def login_page(
    request: Request, user: UserOut | None = Depends(get_current_user)
):
    if user is not None:
        return RedirectResponse(url="/checklist", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request, "auth/login.html", {"error": None}
    )


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    settings: Settings = Depends(get_settings),
    client: asyncpg.Pool = Depends(get_db_client),
):
    try:
        payload = LoginRequest(username=username, password=password)
    except ValidationError:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": "Please enter a username and password."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        user = await auth_service.authenticate_user(
            client, payload.username, payload.password
        )
    except auth_service.InvalidCredentialsError:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": "Invalid username or password."},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    session = await auth_service.create_session(client, user, settings.session_ttl_hours)

    response = RedirectResponse(url="/checklist", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session.token,
        httponly=True,
        samesite="lax",
        max_age=settings.session_ttl_hours * 3600,
    )
    return response


@router.get("/register")
async def register_page(
    request: Request, user: UserOut | None = Depends(get_current_user)
):
    if user is not None:
        return RedirectResponse(url="/checklist", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request, "auth/register.html", {"error": None}
    )


@router.post("/register")
async def register_submit(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    settings: Settings = Depends(get_settings),
    client: asyncpg.Pool = Depends(get_db_client),
):
    try:
        payload = UserCreate(username=username, email=email, password=password)
    except ValidationError as exc:
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {"error": _first_validation_message(exc)},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        user = await auth_service.register_user(client, payload)
    except auth_service.UsernameOrEmailTakenError:
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {"error": "That username or email is already taken."},
            status_code=status.HTTP_409_CONFLICT,
        )

    session = await auth_service.create_session(client, user, settings.session_ttl_hours)

    response = RedirectResponse(url="/checklist", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session.token,
        httponly=True,
        samesite="lax",
        max_age=settings.session_ttl_hours * 3600,
    )
    return response


@router.post("/logout")
async def logout(
    request: Request,
    settings: Settings = Depends(get_settings),
    client: asyncpg.Pool = Depends(get_db_client),
):
    token = request.cookies.get(settings.session_cookie_name)
    if token is not None:
        await auth_service.delete_session(client, token)

    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(key=settings.session_cookie_name)
    return response


def _first_validation_message(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "Invalid input."
    return str(errors[0]["msg"])
