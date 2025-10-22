#!/usr/bin/env bash
# Safe helper to backup DB, run Alembic migration, and verify telemetry sequence.
# Usage: ./scripts/run_resync_migration.sh <DATABASE_URL>

set -euo pipefail

# Accept DATABASE_URL as first arg or from environment
if [ "$#" -eq 1 ]; then
    DATABASE_URL="$1"
elif [ -n "${DATABASE_URL:-}" ]; then
    # use DATABASE_URL from environment
    :
else
    echo "Usage: $0 <DATABASE_URL> or set DATABASE_URL in the environment"
    exit 2
fi
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_FILE="prod_db_backup_${TIMESTAMP}.dump"

if command -v pg_dump >/dev/null 2>&1; then
    echo "Backing up database to $BACKUP_FILE..."
    pg_dump --format=custom --file="$BACKUP_FILE" "$DATABASE_URL"
else
    if [ "${SKIP_BACKUP:-0}" = "1" ]; then
        echo "pg_dump not found; SKIP_BACKUP=1 set, continuing without backup (unsafe)"
    else
        echo "pg_dump not found in PATH. Install pg_dump or set SKIP_BACKUP=1 to skip the backup (unsafe)."
        exit 3
    fi
fi

echo "Running Alembic migrations (upgrade head)..."
# Ensure alembic.ini uses env DATABASE_URL or pass via env
DATABASE_URL="$DATABASE_URL" alembic upgrade head

echo "Verifying extraction_telemetry_v2 sequence..."
PYTHON=$(which python3 || which python)
$PYTHON - <<PY
import os
from sqlalchemy import create_engine, text

url = os.environ.get('DATABASE_URL')
if not url:
    raise SystemExit('DATABASE_URL must be set')
engine = create_engine(url)
with engine.connect() as conn:
    seq_name = conn.execute(text("SELECT pg_get_serial_sequence('extraction_telemetry_v2','id')")).scalar()
    max_id = conn.execute(text("SELECT COALESCE(MAX(id), 0) FROM extraction_telemetry_v2")).scalar()
    print('sequence:', seq_name)
    print('max_id:', max_id)
    if not seq_name:
        raise SystemExit('No sequence found for extraction_telemetry_v2.id')
    val = conn.execute(text(f"SELECT nextval('{seq_name}')")).scalar()
    print('nextval:', val)
    if val < (max_id + 1):
        raise SystemExit('Resync failed: nextval < max_id + 1')
    print('Sequence resync appears successful')

PY

echo 'Done.'
