#!/usr/bin/env bash
# Daily backup of the Panini database (Neon) to private JSON files.
#
#   bash scripts/backup_daily.sh
#
# Safe by construction:
#   * Builds each backup in a hidden temp folder and only renames it into
#     place after it passes checks, so a failed run never leaves something
#     that looks like a good backup.
#   * Never overwrites or deletes an existing backup, except pruning the
#     OLDEST ones beyond the newest BACKUP_KEEP (counted by number, not age,
#     so a long gap in running can't wipe everything).
#   * Locks against overlapping runs; appends every outcome to backup.log.
#
# Restore with:  uv run python -m scripts.import_gel_export <backup_dir> --commit
# (into an EMPTY database). The files hold password hashes and live session
# tokens - keep the folders private.
#
# Settings (environment variables, all optional):
#   PANINI_REPO    checkout holding .env with DATABASE_URL   (default ~/panini-pg)
#   BACKUP_ROOT    where backups are kept                    (default ~/panini-backups/daily)
#   BACKUP_MIRROR  second copy on another filesystem         (default /mnt/c/Users/$USER/panini-backups-daily)
#   BACKUP_KEEP    how many backups to keep                  (default 30)
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"
REPO="${PANINI_REPO:-$HOME/panini-pg}"
ROOT="${BACKUP_ROOT:-$HOME/panini-backups/daily}"
MIRROR="${BACKUP_MIRROR:-/mnt/c/Users/${USER:-$(id -un)}/panini-backups-daily}"
KEEP="${BACKUP_KEEP:-30}"
EXPECTED_STICKERS=992

mkdir -p "$ROOT"
chmod 700 "$ROOT"
LOG="$ROOT/backup.log"
TMP=""

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG"; }

on_exit() {
    local rc=$?
    [ -n "$TMP" ] && rm -rf "$TMP"
    if [ "$rc" -ne 0 ]; then log "FAILED (exit $rc) - no new backup was created; existing backups untouched"; fi
    exit "$rc"
}
trap on_exit EXIT

exec 9>"$ROOT/.lock"
if ! flock -n 9; then
    log "another backup is already running; skipping"
    trap - EXIT
    exit 0
fi

STAMP="$(date -u +%Y-%m-%d_%H%M%S)"
TMP="$ROOT/.tmp-$STAMP"
FINAL="$ROOT/$STAMP"

cd "$REPO"
uv run python -m scripts.export_json "$TMP" >>"$LOG" 2>&1

# Sanity checks before this counts as a backup.
read -r USERS SESSIONS ENTRIES STICKERS < <(python3 - "$TMP" <<'PY'
import json, sys
d = sys.argv[1]
print(*(len(json.load(open(f"{d}/{n}.json"))) for n in
        ("users", "sessions", "collection_entries", "stickers")))
PY
)
if [ "$STICKERS" -ne "$EXPECTED_STICKERS" ]; then
    log "check failed: $STICKERS stickers in export, expected $EXPECTED_STICKERS"; exit 3
fi
if [ "$USERS" -lt 1 ]; then
    log "check failed: export contains no users"; exit 3
fi
(cd "$TMP" && sha256sum ./*.json > SHA256SUMS && sha256sum -c --quiet SHA256SUMS)

# Flag a suspicious drop since the previous backup (kept either way).
PREV="$(find "$ROOT" -maxdepth 1 -type d -name '20??-??-??_??????' | sort | tail -n 1 || true)"
if [ -n "$PREV" ]; then
    read -r PU PE < <(python3 - "$PREV" <<'PY'
import json, sys
d = sys.argv[1]
print(len(json.load(open(f"{d}/users.json"))), len(json.load(open(f"{d}/collection_entries.json"))))
PY
)
    if [ "$USERS" -lt "$PU" ] || [ "$((ENTRIES * 100))" -lt "$((PE * 80))" ]; then
        log "WARNING: previous backup had $PU users / $PE entries, this one $USERS / $ENTRIES - investigate"
    fi
fi

mv "$TMP" "$FINAL"
TMP=""
chmod -R go-rwx "$FINAL"

# Second copy on another filesystem (skipped quietly if its parent is missing).
if [ -d "$(dirname "$MIRROR")" ]; then
    mkdir -p "$MIRROR"
    cp -a "$FINAL" "$MIRROR/"
    (cd "$MIRROR/$STAMP" && sha256sum -c --quiet SHA256SUMS)
    MIRRORED="mirrored"
else
    MIRRORED="NOT mirrored (no $(dirname "$MIRROR"))"
fi

# Keep only the newest $KEEP in both places.
prune() {
    find "$1" -maxdepth 1 -type d -name '20??-??-??_??????' | sort | head -n -"$KEEP" | while read -r old; do
        rm -rf "$old"
    done
}
prune "$ROOT"
[ -d "$MIRROR" ] && prune "$MIRROR"

log "OK users=$USERS sessions=$SESSIONS entries=$ENTRIES stickers=$STICKERS -> $FINAL ($MIRRORED)"
