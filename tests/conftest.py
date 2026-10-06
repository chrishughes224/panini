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

from app.deps import get_db_client
from app.main import app
from app.services.migrations import apply_migrations
from app.services.seeding import seed_catalogue


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
        await pool.close()


@pytest_asyncio.fixture
async def http(pool: asyncpg.Pool) -> AsyncIterator[httpx.AsyncClient]:
    """An ASGI client wired to the test pool (cookies persist per client)."""

    async def _override() -> asyncpg.Pool:
        return pool

    app.dependency_overrides[get_db_client] = _override
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def logged_in(http: httpx.AsyncClient) -> httpx.AsyncClient:
    """`http`, already registered and logged in as a fresh user."""
    response = await http.post(
        "/register",
        data={"username": "alice", "email": "alice@example.com", "password": "correct-horse-1"},
    )
    assert response.status_code == 303
    return http
