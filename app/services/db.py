"""Gel (EdgeDB) client factory.

Kept isolated in its own module so that services depend on a single,
easily-mockable entry point rather than constructing clients themselves.
"""

from __future__ import annotations

from functools import lru_cache

import gel

from app.config import get_settings


@lru_cache(maxsize=1)
def get_client() -> gel.AsyncIOClient:
    """Return a process-wide, connection-pooled async Gel client.

    Cached so the same pooled client is reused across requests. Tests should
    override this dependency rather than calling it directly against a
    production database.
    """
    settings = get_settings()
    return gel.create_async_client(dsn=settings.gel_dsn, branch=settings.gel_branch)
