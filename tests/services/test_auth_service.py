from __future__ import annotations

from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from app.models.user import UserCreate
from app.services import auth_service


def _payload(username: str = "alice", email: str = "alice@example.com") -> UserCreate:
    return UserCreate(username=username, email=email, password="correct-horse-1")


async def test_register_returns_user_and_never_stores_plaintext(pool: asyncpg.Pool) -> None:
    user = await auth_service.register_user(pool, _payload())

    assert user.username == "alice"
    stored = await pool.fetchval("select password_hash from users where id = $1", user.id)
    assert stored != "correct-horse-1"
    assert stored.startswith("$argon2")


@pytest.mark.parametrize(
    ("username", "email"),
    [("alice", "other@example.com"), ("other", "alice@example.com")],
)
async def test_register_rejects_duplicate_username_or_email(
    pool: asyncpg.Pool, username: str, email: str
) -> None:
    await auth_service.register_user(pool, _payload())

    with pytest.raises(auth_service.UsernameOrEmailTakenError):
        await auth_service.register_user(pool, _payload(username, email))


async def test_authenticate_accepts_correct_password(pool: asyncpg.Pool) -> None:
    created = await auth_service.register_user(pool, _payload())

    user = await auth_service.authenticate_user(pool, "alice", "correct-horse-1")

    assert user.id == created.id


@pytest.mark.parametrize(("username", "password"), [("alice", "wrong"), ("nobody", "correct-horse-1")])
async def test_authenticate_rejects_bad_credentials_identically(
    pool: asyncpg.Pool, username: str, password: str
) -> None:
    await auth_service.register_user(pool, _payload())

    with pytest.raises(auth_service.InvalidCredentialsError):
        await auth_service.authenticate_user(pool, username, password)


async def test_session_roundtrip_and_logout(pool: asyncpg.Pool) -> None:
    user = await auth_service.register_user(pool, _payload())
    session = await auth_service.create_session(pool, user, ttl_hours=1)

    resolved = await auth_service.get_user_by_session_token(pool, session.token)
    assert resolved is not None and resolved.id == user.id

    await auth_service.delete_session(pool, session.token)
    assert await auth_service.get_user_by_session_token(pool, session.token) is None


async def test_unknown_session_token_resolves_to_none(pool: asyncpg.Pool) -> None:
    assert await auth_service.get_user_by_session_token(pool, "nope") is None


async def test_expired_session_is_not_valid(pool: asyncpg.Pool) -> None:
    user = await auth_service.register_user(pool, _payload())
    await pool.execute(
        "insert into sessions (token, user_id, expires_at) values ($1, $2, $3)",
        "stale-token",
        user.id,
        datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    assert await auth_service.get_user_by_session_token(pool, "stale-token") is None
