# Panini WC26 Sticker Tracker

A small web app for tracking a physical Panini 2026 FIFA World Cup sticker
collection: what you own, spares to trade, and progress overall and by team.
Multi-user (username/password), data kept per user so it follows you across
devices.

**Stack:** Python 3.12 · FastAPI · Jinja2 + HTMX · Tailwind (CDN) · Postgres
(Neon) via asyncpg · deployed on Vercel.

## Run locally

```bash
uv sync
cp .env.example .env        # then fill in DATABASE_URL etc.
uv run python -m scripts.migrate
uv run python -m scripts.seed_catalogue
uv run uvicorn app.main:app --reload
```

For plain-http local use set `COOKIE_SECURE=false` in `.env`. See
`.env.example` for every setting. Registration is invite-only: leave
`REGISTRATION_CODE` blank to close it, or set a phrase new users must enter.

## Tests

```bash
uv run pytest
```

The suite starts its own throwaway Postgres (no Docker or accounts needed).

## Backups and restore

Neon's free plan keeps only ~6 hours of point-in-time history, so back up
regularly. `scripts/backup_daily.sh` writes a dated, checksummed JSON backup
(keeping the newest 30) and mirrors it to a second location. On the author's
machine it is run daily by a Windows scheduled task. Backups contain password
hashes and live session tokens: keep them private.

Restore into an **empty** database (migrations are applied automatically):

```bash
uv run python -m scripts.import_gel_export <backup_dir>            # dry run
uv run python -m scripts.import_gel_export <backup_dir> --commit   # for real
```

The import preserves every id and verifies each row against the backup before
committing.
