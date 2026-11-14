#!/usr/bin/env bash
# Dumps the production Postgres database, gzips it, and uploads it straight
# to S3 (not kept on the server) — a disk failure or a wiped EC2 instance
# shouldn't be able to take the backups down with it. Prunes backups older
# than RETENTION_DAYS from S3 itself, same idea as a local "find -delete"
# but against the bucket. Not part of the Django app — reads DB and AWS
# credentials straight from the env file rather than importing Django settings.
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

if [[ -z "${AWS_STORAGE_BUCKET_NAME:-}" ]]; then
  echo "[$(date -Iseconds)] AWS_STORAGE_BUCKET_NAME is not set in $ENV_FILE — cannot upload." >&2
  exit 1
fi

# Cron does NOT activate the venv (no login shell, no `source activate`), so
# a bare `python3` on PATH can silently resolve to the system interpreter,
# which won't have boto3. Point at the venv explicitly; verify this path is
# actually where your venv lives on this server (`ls $ROOT_DIR/venv/bin`).
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/venv/bin/python3}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[$(date -Iseconds)] $PYTHON_BIN not found/executable — falling back to 'python3' on PATH (may lack boto3)." >&2
  PYTHON_BIN="python3"
fi

# Local staging dir for the dump before it's uploaded — not the final
# resting place. Cleaned up after a successful upload.
STAGING_DIR="${STAGING_DIR:-/tmp/vehubpro_db_backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
S3_PREFIX="${S3_PREFIX:-db_backups}"

mkdir -p "$STAGING_DIR"

TIMESTAMP="$(date +%Y-%m-%d_%H%M%S)"
DUMP_FILE="$STAGING_DIR/vehubpro_${DB_NAME}_${TIMESTAMP}.sql"

echo "[$(date -Iseconds)] Starting backup of database '${DB_NAME}' -> ${DUMP_FILE}.gz"

cleanup_on_dump_error() {
  echo "[$(date -Iseconds)] Backup FAILED — removing incomplete dump file." >&2
  rm -f "${DUMP_FILE}"
}
trap cleanup_on_dump_error ERR

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
GZ_NAME="$(basename "${GZ_FILE}")"
S3_KEY="${S3_PREFIX}/${GZ_NAME}"

echo "[$(date -Iseconds)] Dump ready ($(du -h "${GZ_FILE}" | cut -f1)) — uploading to s3://${AWS_STORAGE_BUCKET_NAME}/${S3_KEY}"

# Upload + prune old backups from S3 (not local disk) — one Python process,
# using the exact same AWS_* vars just sourced from the env file.
"$PYTHON_BIN" - "$GZ_FILE" "$S3_KEY" <<'PYEOF'
import os
import sys
from datetime import datetime, timedelta, timezone

import boto3

local_path, key = sys.argv[1], sys.argv[2]
bucket = os.environ["AWS_STORAGE_BUCKET_NAME"]
region = os.environ.get("AWS_REGION", "ap-south-1")
prefix = os.environ.get("S3_PREFIX", "db_backups")
retention_days = int(os.environ.get("RETENTION_DAYS", "14"))

s3 = boto3.client(
    "s3",
    region_name=region,
    endpoint_url=f"https://s3.{region}.amazonaws.com",
)

s3.upload_file(local_path, bucket, key)
print(f"Uploaded s3://{bucket}/{key}")

cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
paginator = s3.get_paginator("list_objects_v2")
deleted = []
for page in paginator.paginate(Bucket=bucket, Prefix=f"{prefix}/"):
    for obj in page.get("Contents", []):
        if obj["LastModified"] < cutoff:
            s3.delete_object(Bucket=bucket, Key=obj["Key"])
            deleted.append(obj["Key"])

if deleted:
    print(f"Pruned {len(deleted)} backup(s) older than {retention_days}d:")
    for k in deleted:
        print(" -", k)
PYEOF

echo "[$(date -Iseconds)] Upload complete — removing local staged copy."
rm -f "${GZ_FILE}"

echo "[$(date -Iseconds)] Backup script finished."
