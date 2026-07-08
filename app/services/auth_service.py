"""Service layer for authentication: registration, login, and sessions.

Password hashing uses argon2 (via `argon2-cffi`), which is the current
recommended choice over bcrypt/pbkdf2 for new applications. Sessions are
stored server-side in Gel (a `Session` row per login) rather than as a purely
stateless signed cookie, so that logout / logout-everywhere and expiry are
straightforward to implement and inspect.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import gel
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


async def register_user(client: gel.AsyncIOClient, payload: UserCreate) -> UserOut:
    """Create a new user, raising `UsernameOrEmailTakenError` on conflict."""
    password_hash = hash_password(payload.password)
    try:
        row = await client.query_single(
            """
            select (
                insert User {
                    username := <str>$username,
                    email := <str>$email,
                    password_hash := <str>$password_hash,
                }
            ) { id, username, email, created_at }
            """,
            username=payload.username,
            email=payload.email,
            password_hash=password_hash,
        )
    except gel.ConstraintViolationError as exc:
        raise UsernameOrEmailTakenError(str(exc)) from exc

    return UserOut(
        id=row.id, username=row.username, email=row.email, created_at=row.created_at
    )


async def authenticate_user(
    client: gel.AsyncIOClient, username: str, password: str
) -> UserOut:
    """Verify credentials, raising `InvalidCredentialsError` on any mismatch.

    Deliberately raises the same error for "user not found" and "wrong
    password" so as not to leak which usernames exist.
    """
    row = await client.query_single(
        """
        select User { id, username, email, password_hash, created_at }
        filter .username = <str>$username
        """,
        username=username,
    )
    if row is None or not verify_password(password, row.password_hash):
        raise InvalidCredentialsError("invalid username or password")

    return UserOut(
        id=row.id, username=row.username, email=row.email, created_at=row.created_at
    )


async def create_session(
    client: gel.AsyncIOClient, user: UserOut, ttl_hours: int
) -> SessionOut:
    """Issue a new session token for an already-authenticated user."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)

    await client.query_single(
        """
        insert Session {
            token := <str>$token,
            user := (select User filter .id = <uuid>$user_id),
            expires_at := <datetime>$expires_at,
        }
        """,
        token=token,
        user_id=user.id,
        expires_at=expires_at,
    )
    return SessionOut(token=token, user=user, expires_at=expires_at)


async def get_user_by_session_token(
    client: gel.AsyncIOClient, token: str
) -> UserOut | None:
    """Resolve a session token to its owning user, if the session is valid."""
    row = await client.query_single(
        """
        select Session {
            user: { id, username, email, created_at }
        }
        filter .token = <str>$token and .expires_at > datetime_current()
        """,
        token=token,
    )
    if row is None:
        return None
    user_row = row.user
    return UserOut(
        id=user_row.id,
        username=user_row.username,
        email=user_row.email,
        created_at=user_row.created_at,
    )


async def delete_session(client: gel.AsyncIOClient, token: str) -> None:
    """Log out: delete the session row matching this token, if any."""
    await client.query(
        "delete Session filter .token = <str>$token",
        token=token,
    )
