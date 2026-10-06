"""Service layer for authentication: registration, login, and sessions.

Password hashing uses argon2 (via `argon2-cffi`), which is the current
recommended choice over bcrypt/pbkdf2 for new applications. Sessions are
stored server-side in Postgres (a `sessions` row per login) rather than as a
purely stateless signed cookie, so that logout / logout-everywhere and expiry
are straightforward to implement and inspect.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import asyncpg
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.models.user import SessionOut, UserCreate, UserOut

_hasher = PasswordHasher()


class UsernameOrEmailTakenError(Exception):
    """Raised when registration conflicts with an existing username/email."""


class InvalidCredentialsError(Exception):
    """Raised when login credentials do not match any active user."""


def hash_password(plain_password: str) -> str:
    return _hasher.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, plain_password)
    except VerifyMismatchError:
        return False


def _user_from_row(row: asyncpg.Record) -> UserOut:
    return UserOut(
        id=row["id"],
        username=row["username"],
        email=row["email"],
        created_at=row["created_at"],
    )


async def register_user(db: asyncpg.Pool, payload: UserCreate) -> UserOut:
    """Create a new user, raising `UsernameOrEmailTakenError` on conflict."""
    password_hash = hash_password(payload.password)
    try:
        row = await db.fetchrow(
            """
            insert into users (username, email, password_hash)
            values ($1, $2, $3)
            returning id, username, email, created_at
            """,
            payload.username,
            payload.email,
            password_hash,
        )
    except asyncpg.UniqueViolationError as exc:
        raise UsernameOrEmailTakenError(str(exc)) from exc

    assert row is not None
    return _user_from_row(row)


async def authenticate_user(db: asyncpg.Pool, username: str, password: str) -> UserOut:
    """Verify credentials, raising `InvalidCredentialsError` on any mismatch.

    Deliberately raises the same error for "user not found" and "wrong
    password" so as not to leak which usernames exist.
    """
    row = await db.fetchrow(
        """
        select id, username, email, password_hash, created_at
        from users
        where username = $1
        """,
        username,
    )
    if row is None or not verify_password(password, row["password_hash"]):
        raise InvalidCredentialsError("invalid username or password")

    return _user_from_row(row)


async def create_session(db: asyncpg.Pool, user: UserOut, ttl_hours: int) -> SessionOut:
    """Issue a new session token for an already-authenticated user."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)

    await db.execute(
        "insert into sessions (token, user_id, expires_at) values ($1, $2, $3)",
        token,
        user.id,
        expires_at,
    )
    return SessionOut(token=token, user=user, expires_at=expires_at)


async def get_user_by_session_token(db: asyncpg.Pool, token: str) -> UserOut | None:
    """Resolve a session token to its owning user, if the session is valid."""
    row = await db.fetchrow(
        """
        select u.id, u.username, u.email, u.created_at
        from sessions s
        join users u on u.id = s.user_id
        where s.token = $1 and s.expires_at > now()
        """,
        token,
    )
    if row is None:
        return None
    return _user_from_row(row)


async def delete_session(db: asyncpg.Pool, token: str) -> None:
    """Log out: delete the session row matching this token, if any."""
    await db.execute("delete from sessions where token = $1", token)
