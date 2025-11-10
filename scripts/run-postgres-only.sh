#!/bin/zsh
# Quick Postgres-only test runner
# - Starts docker-compose Postgres
# - Ensures role and test database exist and are owned by the app role
# - Runs Alembic migrations
# - Executes only Postgres/integration-marked tests

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

POSTGRES_SERVICE="mizzou-postgres"
DB_USER="${DB_USER:-mizzou_user}"
DB_PASS="${DB_PASS:-mizzou_pass}"
DB_NAME="${DB_NAME:-news_crawler_test}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"

echo "========================================"
echo "Postgres-only Test Runner"
echo "========================================\n"

# Fallback: ensure Docker binary available on macOS if not in PATH
if ! command -v docker &> /dev/null; then
  export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
fi

echo "[+] Starting docker-compose Postgres (if not running)"
docker compose up -d postgres

echo "[+] Waiting for Postgres to be healthy..."
ATTEMPTS=0
until docker inspect -f '{{.State.Health.Status}}' $POSTGRES_SERVICE 2>/dev/null | grep -q healthy; do
  ATTEMPTS=$((ATTEMPTS+1))
  if [ $ATTEMPTS -gt 30 ]; then
    echo "Postgres container not healthy after timeout"
    docker ps -a
    exit 1
  fi
  sleep 2
done
echo "[✓] Postgres healthy\n"

DEFAULT_DB="${DEFAULT_DB:-mizzou}"
echo "[+] Verifying superuser '$DB_USER' inside container (connecting to '$DEFAULT_DB')"
docker exec -e PGPASSWORD="$DB_PASS" "$POSTGRES_SERVICE" psql -U "$DB_USER" -d "$DEFAULT_DB" -tAc "SELECT current_user;" >/dev/null
echo "[✓] Connected as '$DB_USER'"

echo "[+] Ensuring database '$DB_NAME' exists and is owned by '$DB_USER'"
if ! docker exec -e PGPASSWORD="$DB_PASS" "$POSTGRES_SERVICE" psql -U "$DB_USER" -d "$DEFAULT_DB" -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
  docker exec -e PGPASSWORD="$DB_PASS" "$POSTGRES_SERVICE" psql -U "$DB_USER" -d "$DEFAULT_DB" -v ON_ERROR_STOP=1 -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"
  echo "[✓] Created database '${DB_NAME}' owned by '${DB_USER}'"
else
  echo "[i] Database '${DB_NAME}' already exists; ensuring ownership and privileges"
  docker exec -e PGPASSWORD="$DB_PASS" "$POSTGRES_SERVICE" psql -U "$DB_USER" -d "$DEFAULT_DB" -v ON_ERROR_STOP=1 -c "ALTER DATABASE ${DB_NAME} OWNER TO ${DB_USER};"
fi

echo "[+] Ensuring schema privileges for '$DB_USER' on '${DB_NAME}'"
docker exec -e PGPASSWORD="$DB_PASS" "$POSTGRES_SERVICE" psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -c "GRANT ALL PRIVILEGES ON SCHEMA public TO ${DB_USER};" >/dev/null 2>&1 || true
docker exec -e PGPASSWORD="$DB_PASS" "$POSTGRES_SERVICE" psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -c "ALTER SCHEMA public OWNER TO ${DB_USER};" >/dev/null 2>&1 || true
echo "[✓] Schema privileges ensured\n"

export TEST_DATABASE_URL="postgresql://${DB_USER}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
export DATABASE_URL="$TEST_DATABASE_URL"
export TELEMETRY_DATABASE_URL="$TEST_DATABASE_URL"
export PYTEST_KEEP_DB_ENV="true"

echo "[i] Using DATABASE_URL=$DATABASE_URL"

echo "[+] Running Alembic migrations"
alembic upgrade head
echo "[✓] Migrations complete\n"

echo "[+] Running Postgres integration tests only"
python -m pytest -m integration --tb=short --no-cov tests/
echo "\n[✓] Postgres integration tests passed"

echo "\nDone."
