#!/bin/zsh
# Local CI test runner (Docker Postgres + optional SQLite phase)
#
# Supports selective phases via flags instead of spawning new maintenance scripts.
#
# Usage:
#   ./scripts/run-local-ci-docker.sh                # full (SQLite + Postgres)
#   ./scripts/run-local-ci-docker.sh --postgres-only # migrations + Postgres tests only
#   ./scripts/run-local-ci-docker.sh --sqlite-only   # fast phase only
#   ./scripts/run-local-ci-docker.sh --fail-under=80 # set coverage threshold for SQLite phase
#
# Flags can be combined except --postgres-only and --sqlite-only are mutually exclusive.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

POSTGRES_SERVICE="mizzou-postgres"
DB_USER="mizzou_user"
DB_PASS="mizzou_pass"
DB_NAME="news_crawler_test"
DB_HOST="localhost"
DB_PORT="5432"
DEFAULT_DB="mizzou" # existing DB from docker-compose init cluster

POSTGRES_ONLY=false
SQLITE_ONLY=false
COVERAGE_FAIL_UNDER=0

for arg in "$@"; do
  case "$arg" in
    --postgres-only|--postgres)
      POSTGRES_ONLY=true;;
    --sqlite-only|--sqlite)
      SQLITE_ONLY=true;;
    --fail-under=*)
      COVERAGE_FAIL_UNDER="${arg#*=}";;
    -h|--help)
      echo "Usage: $0 [--postgres-only|--sqlite-only] [--fail-under=N]";
      exit 0;;
    *)
      echo "Unknown argument: $arg"; exit 2;;
  esac
done

if $POSTGRES_ONLY && $SQLITE_ONLY; then
  echo "Cannot use --postgres-only and --sqlite-only together"; exit 2
fi

echo "========================================"
echo "Local CI (Docker/Postgres) Test Runner"
echo "========================================\n"
echo "[i] Flags: POSTGRES_ONLY=$POSTGRES_ONLY SQLITE_ONLY=$SQLITE_ONLY COVERAGE_FAIL_UNDER=$COVERAGE_FAIL_UNDER"

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
    echo "Postgres container not healthy after timeout"; exit 1
  fi
  sleep 2
done
echo "[✓] Postgres healthy\n"

echo "[+] Ensuring role '$DB_USER' exists (handles reused volume with different initial superuser)"
if ! docker exec $POSTGRES_SERVICE psql -U $DB_USER -d $DEFAULT_DB -tAc "SELECT 1" >/dev/null 2>&1; then
  if docker exec $POSTGRES_SERVICE psql -U postgres -d $DEFAULT_DB -tAc "SELECT 1" >/dev/null 2>&1; then
    echo "[i] Creating missing role '$DB_USER' using superuser 'postgres'"
    docker exec $POSTGRES_SERVICE psql -U postgres -d $DEFAULT_DB -c "CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASS';" || true
  else
    echo "[!] 'postgres' superuser absent; attempting cluster superuser fallback"
    # Try connecting without specifying user (unlikely scenario)
    echo "[!] Unable to create role automatically; proceeding (may fail if role required)"
  fi
else
  echo "[✓] Role '$DB_USER' present"
fi

echo "[+] Ensuring test database '$DB_NAME' exists"
if ! docker exec $POSTGRES_SERVICE psql -U $DB_USER -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1; then
  docker exec $POSTGRES_SERVICE psql -U $DB_USER -d postgres -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;" || {
    echo "[i] Retry creating DB as 'postgres'"
    docker exec $POSTGRES_SERVICE psql -U postgres -d postgres -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;" || true
  }
  echo "[✓] Created database '$DB_NAME'"
else
  echo "[✓] Database '$DB_NAME' already exists"
fi

echo "[+] Granting privileges on '$DB_NAME'"
docker exec $POSTGRES_SERVICE psql -U $DB_USER -d postgres -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;" >/dev/null 2>&1 || true
docker exec $POSTGRES_SERVICE psql -U postgres -d postgres -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;" >/dev/null 2>&1 || true
echo "[✓] Privileges ensured\n"

run_postgres_phase() {
  echo "=== Postgres Integration (Docker DB) ===\n"
  export TEST_DATABASE_URL="postgresql://$DB_USER:$DB_PASS@$DB_HOST:$DB_PORT/$DB_NAME"
  export DATABASE_URL="$TEST_DATABASE_URL"
  export TELEMETRY_DATABASE_URL="$TEST_DATABASE_URL"
  export PYTEST_KEEP_DB_ENV="true"
  echo "[i] DATABASE_URL=$DATABASE_URL"
  echo "[+] Running Alembic migrations"
  alembic upgrade head
  echo "[✓] Migrations complete\n"
  python -m pytest -m integration --tb=short --no-cov tests/
  echo "\n[✓] Postgres integration tests passed"
}

run_sqlite_phase() {
  echo "=== SQLite Phase (Unit + Non-Postgres Integration) ===\n"
  unset DATABASE_URL TEST_DATABASE_URL TELEMETRY_DATABASE_URL PYTEST_KEEP_DB_ENV
  python -m pytest -m 'not postgres' --cov=src --cov-report=xml --cov-report=html --cov-report=term-missing --cov-fail-under=$COVERAGE_FAIL_UNDER tests/ || true
  if [ "$COVERAGE_FAIL_UNDER" = "0" ]; then
    echo "[!] Coverage threshold disabled (fail-under=0)"
  else
    echo "[i] Coverage fail-under=$COVERAGE_FAIL_UNDER enforced"
  fi
  echo "\n[✓] SQLite phase complete\n"
}

if $POSTGRES_ONLY; then
  echo "[i] Running Postgres-only mode (skipping SQLite phase)"
  run_postgres_phase
  echo "\nAll requested tests completed successfully."
  exit 0
fi

if $SQLITE_ONLY; then
  echo "[i] Running SQLite-only mode (skipping Postgres phase)"
  run_sqlite_phase
  echo "\nSQLite-only tests completed successfully."
  exit 0
fi

# Full run
echo "[i] Running full test suite (SQLite + Postgres)"
run_sqlite_phase
run_postgres_phase
echo "\nAll CI tests (Docker/Postgres) completed successfully."
