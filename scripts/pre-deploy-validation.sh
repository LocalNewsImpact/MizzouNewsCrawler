#!/bin/bash
set -euo pipefail

#######################################################################
# Pre-Deployment Validation Script
#
# This script runs all critical tests that would catch deployment issues
# BEFORE triggering any Cloud Build or deployment.
#
# Usage:
#   ./scripts/pre-deploy-validation.sh [service] [--dry-run] [--docker-ci]
#
# Examples:
#   ./scripts/pre-deploy-validation.sh processor
#   ./scripts/pre-deploy-validation.sh api
#######################################################################

SERVICE="all"
DRY_RUN=false
DOCKER_CI=false
POSTGRES_ONLY=false
UNIT_DOCKER_ONLY=false
RESET_POSTGRES=false

# Parse args
for arg in "$@"; do
    case "$arg" in
        api|processor|all)
            SERVICE="$arg";;
        --dry-run)
            DRY_RUN=true;;
        --docker-ci)
            DOCKER_CI=true;;
        --postgres-only|--postgres|-postgres)
            POSTGRES_ONLY=true; DOCKER_CI=true;;
        --unit-docker-only|--docker-unit-only|--unit-only-docker)
            UNIT_DOCKER_ONLY=true; DOCKER_CI=true; POSTGRES_ONLY=false;;
        --sqlite-only|--sqlite|-sqlite)
            POSTGRES_ONLY=false; DOCKER_CI=false;;
        --push)
            DO_PUSH=true;;
        --fail-under=*)
            COVERAGE_FAIL_UNDER="${arg#*=}";;
        --branch=*)
            BRANCH_NAME="${arg#*=}";;
        --reset-postgres|--reset-db)
            RESET_POSTGRES=true; DOCKER_CI=true;;
        *)
            echo "Unknown argument: $arg";
            echo "Usage: $0 [service] [--dry-run] [--docker-ci] [--postgres-only] [--sqlite-only] [--push] [--fail-under=N] [--branch=name]";
            exit 2;;
    esac
done
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=========================================="
echo "Pre-Deployment Validation for: ${SERVICE}"
echo "=========================================="
echo ""

if $DRY_RUN; then
    echo "(dry-run mode enabled: git checks will be skipped)"
fi

cd "$PROJECT_ROOT"

# Ensure virtual environment is activated
if [ -z "${VIRTUAL_ENV:-}" ]; then
    echo "⚠️  Virtual environment not active, activating..."
    if [ -d "venv/bin/activate" ]; then
        source venv/bin/activate
    else
        echo "❌ No virtual environment found at venv/"
        exit 1
    fi
fi

echo "✓ Virtual environment active: ${VIRTUAL_ENV}"
echo ""

#######################################################################
## 1. Tests
#######################################################################
echo "=========================================="
echo "1. Running Tests"
echo "=========================================="
echo "Flags: docker-ci=${DOCKER_CI:-false} postgres-only=$POSTGRES_ONLY dry-run=$DRY_RUN"

# Defaults for test phases
: "${COVERAGE_FAIL_UNDER:=0}"
: "${DO_PUSH:=false}"
BRANCH_NAME=${BRANCH_NAME:-$(git branch --show-current 2>/dev/null || echo main)}

run_sqlite_phase() {
    echo "→ Executing fast local tests (non-Docker)"
    PYTEST_DISABLE_MODULE_THRESHOLDS=1 pytest -m 'not postgres' --cov=src --cov-report=term --cov-fail-under=$COVERAGE_FAIL_UNDER -q || {
        echo "❌ Local tests FAILED"; exit 1; }
    echo "✓ Local tests passed"
    echo ""
}

run_postgres_phase() {
    echo "→ Executing Docker-based Postgres tests"
    # Docker setup
    POSTGRES_SERVICE="mizzou-postgres"
    DB_USER="${DB_USER:-mizzou_user}"
    DB_PASS="${DB_PASS:-mizzou_pass}"
    DB_NAME="${DB_NAME:-news_crawler_test}"
    DEFAULT_DB="${DEFAULT_DB:-mizzou}"

    # Ensure Docker binary available on macOS if not in PATH
    if ! command -v docker &> /dev/null; then
        export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
    fi

    echo "[+] Starting docker-compose Postgres (if not running)"
    if $RESET_POSTGRES; then
        echo "[!] RESET_POSTGRES enabled: stopping and removing postgres volume"
        docker compose down -v --remove-orphans || true
    fi
    docker compose up -d postgres

    echo "[+] Waiting for Postgres to be healthy..."
    ATTEMPTS=0
    until docker inspect -f '{{.State.Health.Status}}' "$POSTGRES_SERVICE" 2>/dev/null | grep -q healthy; do
        ATTEMPTS=$((ATTEMPTS+1))
        if [ $ATTEMPTS -gt 30 ]; then
            echo "❌ Postgres container not healthy after timeout"; exit 1
        fi
        sleep 2
    done
    echo "[✓] Postgres healthy"

    # Determine host port mapping for 5432
    # Robustly extract mapped host port for 5432, handling IPv6 and multiple formats
    HOST_PORT=$(docker port "$POSTGRES_SERVICE" 5432/tcp 2>/dev/null | head -n1 | sed -E 's/.*:([0-9]+)$/\1/')
    if [ -z "$HOST_PORT" ]; then
        echo "[!] No published host port for 5432 detected. Likely host port 5432 is already in use."
        echo "    Attempting to re-publish container with a random host port..."
        TMP_OVERRIDE=$(mktemp)
        cat > "$TMP_OVERRIDE" <<'YAML'
services:
  postgres:
    ports:
      - "0:5432"
YAML
        docker compose -f docker-compose.yml -f "$TMP_OVERRIDE" up -d postgres
        # Re-wait for health (container may be recreated)
        ATTEMPTS=0
        until docker inspect -f '{{.State.Health.Status}}' "$POSTGRES_SERVICE" 2>/dev/null | grep -q healthy; do
            ATTEMPTS=$((ATTEMPTS+1))
            if [ $ATTEMPTS -gt 30 ]; then
                echo "❌ Postgres container not healthy after remap timeout"; rm -f "$TMP_OVERRIDE"; exit 1
            fi
            sleep 2
        done
        HOST_PORT=$(docker port "$POSTGRES_SERVICE" 5432/tcp 2>/dev/null | head -n1 | sed -E 's/.*:([0-9]+)$/\1/')
        if [ -z "$HOST_PORT" ]; then
            echo "❌ Unable to determine published host port for Postgres after remap."
            echo "   Ensure no local Postgres is binding 5432, or stop it and retry."
            rm -f "$TMP_OVERRIDE"
            exit 1
        fi
        rm -f "$TMP_OVERRIDE"
    fi
    DB_HOST="127.0.0.1"
    DB_PORT="$HOST_PORT"

    echo "[i] Using host ${DB_HOST}:${DB_PORT}"

                        echo "[+] Detecting existing superuser and ensuring role '$DB_USER' and database '$DB_NAME'"
                        DESIRED_ROLE="mizzou_user"
                        DESIRED_PASS="mizzou_pass"

                        # Probe for an existing superuser in the cluster (volume may predate env changes)
                        USER_CANDIDATES=("mizzou_user" "postgres")
                        PASS_CANDIDATES=("${DESIRED_PASS}" "postgres" "")
                        SUPERUSER=""
                        SUPERPASS=""
                        for u in "${USER_CANDIDATES[@]}"; do
                            for p in "${PASS_CANDIDATES[@]}"; do
                                if docker exec -e PGPASSWORD="$p" "$POSTGRES_SERVICE" psql -U "$u" -d postgres -c "SELECT 1;" >/dev/null 2>&1; then
                                    SUPERUSER="$u"
                                    SUPERPASS="$p"
                                    break 2
                                fi
                            done
                        done
                        if [ -z "$SUPERUSER" ]; then
                            echo "❌ Unable to identify a working superuser in container. Consider --reset-postgres to reinitialize cluster."
                            exit 1
                        fi
                        echo "[i] Detected superuser inside container: $SUPERUSER"

                        # Ensure desired role exists (mizzou_user) regardless of which superuser we connected with
                        if docker exec -e PGPASSWORD="$SUPERPASS" "$POSTGRES_SERVICE" psql -U "$SUPERUSER" -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DESIRED_ROLE}'" | grep -q 1; then
                            echo "[i] Role '$DESIRED_ROLE' already present"
                        else
                            echo "[+] Creating role '$DESIRED_ROLE'"
                            docker exec -e PGPASSWORD="$SUPERPASS" "$POSTGRES_SERVICE" psql -U "$SUPERUSER" -d postgres -v ON_ERROR_STOP=1 -c "CREATE ROLE ${DESIRED_ROLE} WITH LOGIN PASSWORD '${DESIRED_PASS}' SUPERUSER;" || {
                                echo "❌ Failed to create required role '${DESIRED_ROLE}'"; exit 1; }
                        fi

                        # Adopt desired role for tests
                        DB_USER="$DESIRED_ROLE"
                        DB_PASS="$DESIRED_PASS"

                        # Ensure test database exists owned by desired role
                        if docker exec -e PGPASSWORD="$SUPERPASS" "$POSTGRES_SERVICE" psql -U "$SUPERUSER" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
                            echo "[i] Database '$DB_NAME' already exists"
                        else
                            echo "[+] Creating test database '$DB_NAME' owned by '$DB_USER'"
                            docker exec -e PGPASSWORD="$SUPERPASS" "$POSTGRES_SERVICE" psql -U "$SUPERUSER" -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};" || {
                                echo "❌ Failed to create database '${DB_NAME}'"; exit 1; }
                        fi

                        echo "[+] Introspection: listing roles (filtered)"
                        docker exec -e PGPASSWORD="$SUPERPASS" "$POSTGRES_SERVICE" psql -U "$SUPERUSER" -d postgres -c "\du" | head -50 || true
                        echo "[+] Introspection: \conninfo"
                        docker exec -e PGPASSWORD="$SUPERPASS" "$POSTGRES_SERVICE" psql -U "$SUPERUSER" -d postgres -c "\conninfo" || true

                        echo "[+] Verifying connectivity as '$DB_USER' to database '$DB_NAME'"
                        if docker exec -e PGPASSWORD="$DB_PASS" "$POSTGRES_SERVICE" psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT current_user, current_database();" >/dev/null 2>&1; then
                            echo "[✓] Connectivity verified for role '$DB_USER'"
                        else
                            echo "❌ Connectivity test failed for role '$DB_USER' to '$DB_NAME'"; exit 1
                        fi

    export TEST_DATABASE_URL="postgresql://$DB_USER:$DB_PASS@$DB_HOST:$DB_PORT/$DB_NAME"
    export DATABASE_URL="$TEST_DATABASE_URL"
    export TELEMETRY_DATABASE_URL="$TEST_DATABASE_URL"
    # Provide component vars too to avoid mis-detection in some code paths
    export DATABASE_ENGINE="postgresql+psycopg2"
    export DATABASE_HOST="$DB_HOST"
    export DATABASE_PORT="$DB_PORT"
    export DATABASE_NAME="$DB_NAME"
    export DATABASE_USER="$DB_USER"
    export DATABASE_PASSWORD="$DB_PASS"
    export PYTEST_KEEP_DB_ENV="true"
    # Force Alembic to use DATABASE_URL path, not Cloud SQL connector
    export USE_CLOUD_SQL_CONNECTOR="false"
    unset CLOUD_SQL_INSTANCE
    echo "[i] DATABASE_URL=$DATABASE_URL"

        echo "[+] Preflight connectivity check from host (quiet)"
        if ! python - <<'PY'
import os, sys
from sqlalchemy import create_engine, text
url = os.environ.get('DATABASE_URL')
if not url:
    print('[preflight] ERROR: DATABASE_URL missing')
    sys.exit(2)
try:
    engine = create_engine(url)
    with engine.connect() as conn:
        v = conn.execute(text('select version(), current_user')).fetchone()
        print('[preflight] Server:', v[0].split('\n')[0])
        print('[preflight] User:', v[1])
except Exception as e:  # noqa: BLE001
    # Emit concise summary only (suppress full traceback spam)
    msg = str(e).split('\n')[-1]
    print(f'[preflight] connectivity failed: {e.__class__.__name__}: {msg}')
    sys.exit(1)
PY
        then
            echo "[!] Host connectivity failed (likely local Postgres on 5432). Launching isolated ephemeral Postgres container for tests."
            EPHEMERAL_CONTAINER="predeploy-postgres-test"
            docker rm -f "$EPHEMERAL_CONTAINER" >/dev/null 2>&1 || true
            docker run -d --name "$EPHEMERAL_CONTAINER" \
                -e POSTGRES_USER=mizzou_user \
                -e POSTGRES_PASSWORD=mizzou_pass \
                -e POSTGRES_DB=news_crawler_test \
                -p 0:5432 postgres:16 >/dev/null

            echo "[+] Waiting for ephemeral Postgres to become ready..."
            ATT=0
            until docker exec "$EPHEMERAL_CONTAINER" pg_isready -U mizzou_user -d news_crawler_test >/dev/null 2>&1; do
                ATT=$((ATT+1))
                if [ $ATT -gt 30 ]; then
                    echo "❌ Ephemeral Postgres failed to become ready"; exit 1
                fi
                sleep 1
            done
            EPHEMERAL_PORT=$(docker port "$EPHEMERAL_CONTAINER" 5432/tcp 2>/dev/null | head -n1 | sed -E 's/.*:([0-9]+)$/\1/')
            if [ -z "$EPHEMERAL_PORT" ]; then
                echo "❌ Could not determine ephemeral Postgres host port"; exit 1
            fi
            DB_HOST=127.0.0.1
            DB_PORT="$EPHEMERAL_PORT"
            DB_NAME=news_crawler_test
            DB_USER=mizzou_user
            DB_PASS=mizzou_pass
            export TEST_DATABASE_URL="postgresql://$DB_USER:$DB_PASS@$DB_HOST:$DB_PORT/$DB_NAME"
            export DATABASE_URL="$TEST_DATABASE_URL"
            export TELEMETRY_DATABASE_URL="$TEST_DATABASE_URL"
            export DATABASE_HOST="$DB_HOST"
            export DATABASE_PORT="$DB_PORT"
            echo "[i] Using ephemeral Postgres container '$EPHEMERAL_CONTAINER' on port $DB_PORT"
            # Connectivity attempt
            python - <<'PY'
import os, sys
from sqlalchemy import create_engine, text
url = os.environ.get('DATABASE_URL')
engine = create_engine(url)
with engine.connect() as conn:
        v = conn.execute(text('select version(), current_user')).fetchone()
        print('Ephemeral server info:', v[0].split('\n')[0])
        print('Ephemeral current user:', v[1])
PY
        fi

    echo "[+] Running Alembic migrations"
    alembic upgrade head
    echo "[✓] Migrations complete"

    # Allow narrowing test selection to speed up iteration:
    # - Set PYTEST_TESTS to a path or list of tests (default: tests/)
    # - Set PYTEST_K to a -k expression to further filter
    TEST_SELECTION=${PYTEST_TESTS:-tests/}
    if [ -n "${PYTEST_K:-}" ]; then
        echo "[i] Running subset: $TEST_SELECTION with -k '$PYTEST_K'"
        python -m pytest -m integration --tb=short --no-cov -k "$PYTEST_K" $TEST_SELECTION
    else
        echo "[i] Running selection: $TEST_SELECTION"
        python -m pytest -m integration --tb=short --no-cov $TEST_SELECTION
    fi
    echo "✓ Postgres integration tests passed"
    echo ""
}

# Run unit (non-integration, non-postgres) tests inside a disposable Docker container
run_unit_docker_phase() {
    echo "→ Executing unit tests inside Docker (isolated)"
    # Use slim python image and install deps each run. For speed, allow caching layers later by
    # optionally building a dedicated image, but keep it simple here.
    # Avoid integration + postgres markers; rely on test markers, not DB.
    UNIT_MARKERS="not integration and not postgres"
    # Respect COVERAGE_FAIL_UNDER only if non-zero; skip coverage for speed unless explicitly set.
    COVERAGE_ARGS=""
    NO_COV="--no-cov"
    if [ "${COVERAGE_FAIL_UNDER:-0}" != "0" ]; then
        COVERAGE_ARGS="--cov=src --cov-report=term --cov-fail-under=${COVERAGE_FAIL_UNDER}"
        NO_COV=""  # when explicit coverage requested, don't disable it
    fi
    echo "[i] Marker expression: ${UNIT_MARKERS}"
    echo "[i] Coverage args: ${COVERAGE_ARGS:-<none>}"
    # Compose the test command executed inside container using existing base image
    # Load repo pytest.ini to register custom markers (prevents UnknownMark warnings)
    # Limit collection to tests/ to avoid manual/dev tests under scripts/ and others.
    TEST_SELECTION="${PYTEST_TESTS:-tests/}"
    # Allow overriding the marker expression from the host via UNIT_MARKERS_OVERRIDE
    EFFECTIVE_EXPR="${UNIT_MARKERS_OVERRIDE:-$UNIT_MARKERS}"
    TEST_CMD="set -euo pipefail; echo '[i] Marker expression (effective):' '${EFFECTIVE_EXPR}'; pytest -m '${EFFECTIVE_EXPR}' ${COVERAGE_ARGS} ${NO_COV} -q ${TEST_SELECTION}"

    # Ensure docker CLI available (macOS Docker Desktop path fallback + optional DOCKER_BIN override)
    if ! command -v docker >/dev/null 2>&1; then
        if [ -n "${DOCKER_BIN:-}" ] && [ -x "${DOCKER_BIN}" ]; then
            export PATH="$(dirname "${DOCKER_BIN}"):$PATH"
        fi
    fi
    if ! command -v docker >/dev/null 2>&1; then
        if [ -d "/Applications/Docker.app/Contents/Resources/bin" ]; then
            export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
        fi
    fi
    if ! command -v docker >/dev/null 2>&1; then
        echo "❌ Docker is required for --unit-docker-only phase but not found in PATH after attempting common locations"; exit 1;
    fi
    # Run in existing base image, mounting workspace at /app (matches base WORKDIR)
    docker run --rm -e UNIT_MARKERS_OVERRIDE -v "$PWD":/app -w /app mizzou-base:latest bash -lc "$TEST_CMD" || {
        echo "❌ Unit tests (Docker) FAILED"; exit 1; }
    echo "✓ Unit (Docker) tests passed"
    echo ""
}

if $DOCKER_CI; then
    if $UNIT_DOCKER_ONLY; then
        run_unit_docker_phase
    elif $POSTGRES_ONLY; then
        run_postgres_phase
    else
        run_sqlite_phase
        run_postgres_phase
    fi
else
    run_sqlite_phase
fi

#######################################################################
# 3. Deployment YAML Validation
#######################################################################
echo "=========================================="
echo "3. Validating Deployment Configuration"
echo "=========================================="

if [ "$SERVICE" = "processor" ] || [ "$SERVICE" = "all" ]; then
    echo "Checking processor-deployment.yaml..."
    
    # Check PYTHONPATH includes /app
    if ! grep -q 'value: "/app:' k8s/processor-deployment.yaml; then
        echo "❌ PYTHONPATH does not include /app!"
        echo "   This will cause ModuleNotFoundError for src imports"
        echo ""
        echo "   Current PYTHONPATH:"
        grep -A1 "name: PYTHONPATH" k8s/processor-deployment.yaml || echo "   Not found!"
        echo ""
        echo "   Expected: value: \"/app:/opt/origin-shim\""
        exit 1
    fi
    
    # Check image is a placeholder (not :latest)
    if grep -q 'image:.*:latest' k8s/processor-deployment.yaml; then
        echo "❌ Deployment uses image:latest!"
        echo "   This prevents Cloud Deploy from updating pods"
        echo "   Use placeholder like 'image: processor' instead"
        exit 1
    fi
    
    # Check CPU limits are reasonable
    if grep -q 'cpu:.*[0-9]\+m' k8s/processor-deployment.yaml; then
        cpu_request=$(grep -A1 "requests:" k8s/processor-deployment.yaml | grep "cpu:" | awk '{print $2}' | tr -d '"')
        cpu_limit=$(grep -A1 "limits:" k8s/processor-deployment.yaml | grep "cpu:" | awk '{print $2}' | tr -d '"')
        
        echo "  CPU request: ${cpu_request}"
        echo "  CPU limit: ${cpu_limit}"
    fi
    
    echo "✓ Deployment YAML validation passed"
    echo ""
fi

#######################################################################
# 4. Skaffold Configuration Validation
#######################################################################
echo "=========================================="
echo "4. Validating Skaffold Configuration"
echo "=========================================="

if [ -f "skaffold.yaml" ]; then
    # Check that processor artifact is defined
    if ! grep -q 'image: processor' skaffold.yaml; then
        echo "❌ Skaffold config missing processor artifact!"
        exit 1
    fi
    
    # Check that manifests are defined
    if ! grep -q 'rawYaml:' skaffold.yaml; then
        echo "❌ Skaffold config missing manifest paths!"
        exit 1
    fi
    
    echo "✓ Skaffold configuration valid"
    echo ""
else
    echo "⚠️  No skaffold.yaml found (may be optional)"
    echo ""
fi

#######################################################################
# 5. Cloud Build Configuration Validation
#######################################################################
echo "=========================================="
echo "5. Validating Cloud Build Configuration"
echo "=========================================="

if [ "$SERVICE" = "processor" ] || [ "$SERVICE" = "all" ]; then
    if [ ! -f "gcp/cloudbuild/cloudbuild-processor.yaml" ]; then
        echo "❌ gcp/cloudbuild/cloudbuild-processor.yaml not found!"
        exit 1
    fi
    
    # Check that it uses Skaffold rendering
    if ! grep -q '\-\-skaffold\-file' gcp/cloudbuild/cloudbuild-processor.yaml; then
        echo "❌ Cloud Build config doesn't use Skaffold rendering!"
        echo "   Add --skaffold-file=skaffold.yaml to release creation"
        exit 1
    fi
    
    echo "✓ Cloud Build configuration valid"
    echo ""
fi

#######################################################################
# 6. Git Status Check (skippable in dry-run)
#######################################################################
echo "=========================================="
echo "6. Checking Git Status"
echo "=========================================="

if ! $DRY_RUN; then
    if [ -n "$(git status --porcelain)" ]; then
            echo "⚠️  Uncommitted changes detected:"
            git status --short
            echo ""
            echo "❌ Commit and push all changes before deploying!"
            echo ""
            echo "Run:"
            echo "  git add ."
            echo "  git commit -m 'Your commit message'"
            echo "  git push origin $(git branch --show-current)"
            echo ""
            exit 1
    fi

    echo "✓ All changes committed"
    echo ""

    # Check if current branch is pushed
    if ! git diff --quiet origin/$(git branch --show-current) 2>/dev/null; then
            echo "⚠️  Local branch ahead of origin"
            echo "❌ Push changes before deploying!"
            echo ""
            echo "Run:"
            echo "  git push origin $(git branch --show-current)"
            echo ""
            exit 1
    fi

    echo "✓ Branch up to date with origin"
    echo ""
else
    echo "(dry-run) Skipping git cleanliness and origin checks"
    echo ""
fi

#######################################################################
# Summary
#######################################################################
echo "=========================================="
echo "✅ PRE-DEPLOYMENT VALIDATION PASSED"
echo "=========================================="
echo ""
echo "All checks passed! Safe to deploy ${SERVICE}."
echo ""
echo "To deploy, run:"
if $DRY_RUN && [ "${DO_PUSH}" = true ]; then
    echo "  (dry-run) --push specified, but push suppressed"
elif $DRY_RUN; then
    echo "  (dry-run) Deployment command suppressed"
elif [ "${DO_PUSH}" = true ]; then
    echo "  Triggering Cloud Build for ${SERVICE} on branch ${BRANCH_NAME}"
    case "$SERVICE" in
        api)
            gcloud builds triggers run build-api-manual --branch="$BRANCH_NAME" ;;
        processor)
            gcloud builds triggers run build-processor-manual --branch="$BRANCH_NAME" ;;
        crawler)
            gcloud builds triggers run build-crawler-manual --branch="$BRANCH_NAME" ;;
        all)
            gcloud builds triggers run build-api-manual --branch="$BRANCH_NAME"
            gcloud builds triggers run build-crawler-manual --branch="$BRANCH_NAME"
            gcloud builds triggers run build-processor-manual --branch="$BRANCH_NAME" ;;
        *)
            echo "Unknown service '$SERVICE' for push" ;;
    esac
    echo "  (push triggered)"
else
    echo "  gcloud builds triggers run build-${SERVICE}-manual --branch=${BRANCH_NAME}"
fi
echo ""
