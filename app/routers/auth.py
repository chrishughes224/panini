"""Auth router: registration, login, logout.

Renders full pages (not HTMX fragments) since these are entry/exit points to
the app rather than in-page interactions.

Hardening (the app is internet-facing):
  * Registration is invite-only: closed unless REGISTRATION_CODE is set, and
    sign-up then requires that code.
  * Failed logins and failed invite codes are rate-limited (see
    `app.services.rate_limit`), per username and per client address.
  * The session cookie is `Secure` unless COOKIE_SECURE=false.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

import asyncpg
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse, Response
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.deps import get_db_client, get_current_user
from app.models.user import LoginRequest, UserCreate, UserOut
from app.services import auth_service, rate_limit
from app.templating import templates

router = APIRouter(tags=["auth"])

_TOO_MANY = "Too many failed attempts. Please wait a few minutes and try again."


def _registration_open(settings: Settings) -> bool:
    return bool(settings.registration_code)


def _window(settings: Settings) -> timedelta:
    return timedelta(minutes=settings.rate_limit_window_minutes)


def _client_ip(request: Request, settings: Settings) -> str:
    """Best-effort client address for rate limiting.

    The X-Forwarded-For header is only honoured when TRUST_FORWARDED_FOR is
    set, i.e. when running behind a proxy (Vercel) that overwrites it.
    """
    if settings.trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_hours * 3600,
    )


def _too_many_response(request: Request, template: str, settings: Settings) -> Response:
    return templates.TemplateResponse(
        request,
        template,
        {"error": _TOO_MANY, "registration_open": _registration_open(settings)},
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        headers={"Retry-After": str(settings.rate_limit_window_minutes * 60)},
    )


@router.get("/login")
async def login_page(
    request: Request,
    user: UserOut | None = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    if user is not None:
        return RedirectResponse(url="/checklist", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {"error": None, "registration_open": _registration_open(settings)},
    )


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    settings: Settings = Depends(get_settings),
    client: asyncpg.Pool = Depends(get_db_client),
):
    open_ = _registration_open(settings)
    try:
        payload = LoginRequest(username=username, password=password)
    except ValidationError:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": "Please enter a username and password.", "registration_open": open_},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user_key = payload.username.lower()
    ip_key = _client_ip(request, settings)
    window = _window(settings)
    if await rate_limit.is_blocked(
        client, rate_limit.KIND_LOGIN_USER, user_key,
        limit=settings.login_max_failures_per_username, window=window,
    ) or await rate_limit.is_blocked(
        client, rate_limit.KIND_LOGIN_IP, ip_key,
        limit=settings.login_max_failures_per_ip, window=window,
    ):
        return _too_many_response(request, "auth/login.html", settings)

    try:
        user = await auth_service.authenticate_user(
            client, payload.username, payload.password
        )
    except auth_service.InvalidCredentialsError:
        await rate_limit.record_failure(client, rate_limit.KIND_LOGIN_USER, user_key)
        await rate_limit.record_failure(client, rate_limit.KIND_LOGIN_IP, ip_key)
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": "Invalid username or password.", "registration_open": open_},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    await rate_limit.clear(client, rate_limit.KIND_LOGIN_USER, user_key)
    session = await auth_service.create_session(client, user, settings.session_ttl_hours)

    response = RedirectResponse(url="/checklist", status_code=status.HTTP_303_SEE_OTHER)
    _set_session_cookie(response, settings, session.token)
    return response


@router.get("/register")
async def register_page(
    request: Request,
    user: UserOut | None = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    if user is not None:
        return RedirectResponse(url="/checklist", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request,
        "auth/register.html",
        {"error": None, "registration_open": _registration_open(settings)},
    )


@router.post("/register")
async def register_submit(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    invite_code: str = Form(""),
    settings: Settings = Depends(get_settings),
    client: asyncpg.Pool = Depends(get_db_client),
):
    if not _registration_open(settings):
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {"error": None, "registration_open": False},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    ip_key = _client_ip(request, settings)
    if await rate_limit.is_blocked(
        client, rate_limit.KIND_REGISTER_IP, ip_key,
        limit=settings.register_max_failures_per_ip, window=_window(settings),
    ):
        return _too_many_response(request, "auth/register.html", settings)

    # Constant-time comparison; checked before anything else so a wrong code
    # never reveals whether a username or email is already taken.
    if not secrets.compare_digest(
        invite_code.strip().encode(), settings.registration_code.encode()
    ):
        await rate_limit.record_failure(client, rate_limit.KIND_REGISTER_IP, ip_key)
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {"error": "That invite code isn't valid.", "registration_open": True},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    try:
        payload = UserCreate(username=username, email=email, password=password)
    except ValidationError as exc:
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {"error": _first_validation_message(exc), "registration_open": True},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        user = await auth_service.register_user(client, payload)
    except auth_service.UsernameOrEmailTakenError:
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {"error": "That username or email is already taken.", "registration_open": True},
            status_code=status.HTTP_409_CONFLICT,
        )

    session = await auth_service.create_session(client, user, settings.session_ttl_hours)

    response = RedirectResponse(url="/checklist", status_code=status.HTTP_303_SEE_OTHER)
    _set_session_cookie(response, settings, session.token)
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
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return response


def _first_validation_message(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "Invalid input."
    return str(errors[0]["msg"])
