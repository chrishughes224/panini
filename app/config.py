"""Application configuration, loaded from environment variables / .env.

All configuration is strictly typed via pydantic-settings so misconfiguration
fails fast at startup rather than surfacing as a runtime error deep in a
request handler.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strictly typed application settings.

    Values are sourced from environment variables (or a local `.env` file)
    and validated on process startup.
    """

    # `extra="ignore"`: a local .env may still carry leftover keys (e.g. the
    # retired GEL_DSN) which must not stop the app from starting.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    host: str = "192.168.1.170"
    port: int = 8003

    # Postgres connection string. On Neon, use the *pooled* connection string
    # (the host contains "-pooler"), e.g.
    #   postgresql://user:pass@ep-xxx-pooler.region.aws.neon.tech/neondb?sslmode=require
    database_url: str = ""
    # Per-process pool size. Kept small: on a serverless platform every warm
    # instance holds its own pool, and Neon's pooler multiplexes them.
    db_pool_max_size: int = 5

    session_cookie_name: str = "panini_session"
    session_ttl_hours: int = 24 * 30  # 30 days
    # Send the session cookie only over HTTPS. Keep True in production; set
    # COOKIE_SECURE=false only for plain-http local/LAN development.
    cookie_secure: bool = True

    # Invite-only registration. Blank (the default) means registration is
    # closed; set it to a secret phrase and new users must enter it to sign up.
    registration_code: str = ""

    # Brute-force protection (counted in the database so it works across
    # serverless instances). Failures are counted inside the sliding window.
    rate_limit_window_minutes: int = 15
    login_max_failures_per_username: int = 10
    login_max_failures_per_ip: int = 30
    register_max_failures_per_ip: int = 10
    # Only enable behind a proxy that overwrites X-Forwarded-For (e.g. Vercel);
    # otherwise a client could spoof its address to dodge the per-IP limit.
    trust_forwarded_for: bool = False

    # Used for signing/validating anything that needs a shared secret beyond
    # the DB-backed session token (kept for future use, e.g. CSRF tokens).
    secret_key: str = "change-me-in-.env"


def get_settings() -> Settings:
    """Return the process-wide settings instance.

    A thin function wrapper (rather than a bare module-level constant) so it
    can be swapped via FastAPI's dependency-override mechanism in tests.
    """
    return Settings()
