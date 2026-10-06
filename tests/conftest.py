"""Shared fixtures: a throwaway local Postgres with the real schema + catalogue.

`pgserver` bundles Postgres binaries, so the suite needs no Docker, system
Postgres or network. The server is started once per session; each test gets
its own asyncpg pool and a clean slate for user-owned data (the 992-sticker
catalogue is seeded once and left in place).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import asyncpg
import httpx
import pgserver
import pytest
import pytest_asyncio

from app.config import Settings, get_settings
from app.deps import get_db_client
from app.main import app
from app.services.migrations import apply_migrations
from app.services.seeding import seed_catalogue

INVITE_CODE = "test-invite"


async def _prepare_database(uri: str) -> None:
    pool = await asyncpg.create_pool(uri, min_size=1, max_size=2, statement_cache_size=0)
    try:
        async with pool.acquire() as conn:
            await apply_migrations(conn)
        await seed_catalogue(pool)
    finally:
        await pool.close()


@pytest.fixture(scope="session")
def database_uri(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    data_dir: Path = tmp_path_factory.mktemp("pgdata")
    server = pgserver.get_server(data_dir, cleanup_mode="stop")  # type: ignore[attr-defined]
    uri = server.get_uri()
    asyncio.run(_prepare_database(uri))
    try:
        yield uri
    finally:
        server.cleanup()


@pytest_asyncio.fixture
async def pool(database_uri: str) -> AsyncIterator[asyncpg.Pool]:
    pool = await asyncpg.create_pool(
        database_uri, min_size=1, max_size=4, statement_cache_size=0
    )
    try:
        yield pool
    finally:
        # Cascades to sessions and collection_entries; stickers are kept.
        await pool.execute("truncate users cascade")
        await pool.execute("truncate auth_failures")
        await pool.close()


@pytest.fixture
def settings() -> Settings:
    """Test settings: isolated from any real .env, invite code set, small
    rate-limit thresholds so those tests stay fast. Tests may mutate it."""
    return Settings(
        _env_file=None,
        database_url="",
        registration_code=INVITE_CODE,
        cookie_secure=True,
        trust_forwarded_for=True,
        login_max_failures_per_username=3,
        login_max_failures_per_ip=5,
        register_max_failures_per_ip=3,
    )


@pytest_asyncio.fixture
async def http(pool: asyncpg.Pool, settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """An ASGI client wired to the test pool/settings (cookies persist per client).

    Uses an https base URL because the session cookie is `Secure`.
    """

    async def _db() -> asyncpg.Pool:
        return pool

    app.dependency_overrides[get_db_client] = _db
    app.dependency_overrides[get_settings] = lambda: settings
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def logged_in(http: httpx.AsyncClient) -> httpx.AsyncClient:
    """`http`, already registered and logged in as a fresh user."""
    response = await http.post(
        "/register",
        data={
            "username": "alice",
            "email": "alice@example.com",
            "password": "correct-horse-1",
            "invite_code": INVITE_CODE,
        },
    )
    assert response.status_code == 303
    return http
