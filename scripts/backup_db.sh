#!/usr/bin/env bash
# Dumps the production Postgres database, gzips it, and prunes old backups.
# Intended to run via cron (see scripts/README or the setup instructions
# given alongside this file) — not part of the Django app itself, so it
# reads DB credentials straight from the env file rather than importing
# Django settings.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # backend/

export DJANGO_ENV="${DJANGO_ENV:-prod}"
ENV_FILE="$ROOT_DIR/config/.env.${DJANGO_ENV}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[$(date -Iseconds)] Env file not found: $ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# Two levels above backend/ by default — outside the project folder entirely
# (e.g. ROOT_DIR=/opt/vehubpro/backend -> /opt/backups, a sibling of
# /opt/vehubpro, not nested inside it). Override with BACKUP_DIR if you want
# it elsewhere (e.g. a mounted volume).
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/../../backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

mkdir -p "$BACKUP_DIR"

TIMESTAMP="$(date +%Y-%m-%d_%H%M%S)"
DUMP_FILE="$BACKUP_DIR/vehubpro_${DB_NAME}_${TIMESTAMP}.sql"

echo "[$(date -Iseconds)] Starting backup of database '${DB_NAME}' -> ${DUMP_FILE}.gz"

cleanup_on_error() {
  echo "[$(date -Iseconds)] Backup FAILED — removing incomplete dump file." >&2
  rm -f "${DUMP_FILE}"
}
trap cleanup_on_error ERR

export PGPASSWORD="${DB_PASSWORD}"
pg_dump \
  --host="${DB_HOST}" \
  --port="${DB_PORT}" \
  --username="${DB_USER}" \
  --format=plain \
  --no-owner \
  --no-privileges \
  "${DB_NAME}" > "${DUMP_FILE}"
unset PGPASSWORD

trap - ERR

gzip -f "${DUMP_FILE}"
GZ_FILE="${DUMP_FILE}.gz"

echo "[$(date -Iseconds)] Backup complete: ${GZ_FILE} ($(du -h "${GZ_FILE}" | cut -f1))"

# Retention: delete backups older than RETENTION_DAYS so this folder doesn't
# grow forever. Override by exporting RETENTION_DAYS before calling this script.
DELETED="$(find "${BACKUP_DIR}" -name "vehubpro_*.sql.gz" -type f -mtime +"${RETENTION_DAYS}" -print -delete)"
if [[ -n "${DELETED}" ]]; then
  echo "[$(date -Iseconds)] Pruned old backups (older than ${RETENTION_DAYS}d):"
  echo "${DELETED}"
fi

echo "[$(date -Iseconds)] Backup script finished."
