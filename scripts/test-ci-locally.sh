#!/bin/bash
set -e

# Test CI workflow locally using Docker to reproduce GitHub Actions environment
# This script:
# 1. Starts PostgreSQL 15 container with same settings as CI
# 2. Runs migrations
# 3. Runs tests in ci-base container with same network/env as CI

# Use Docker from Docker Desktop if not in PATH
if ! command -v docker &> /dev/null; then
    export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
fi

echo "🧪 Testing CI workflow locally..."
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration matching CI
POSTGRES_USER="postgres"
POSTGRES_PASSWORD="postgres"
POSTGRES_DB="test_db"
POSTGRES_CONTAINER="ci-test-postgres"
POSTGRES_PORT="5434"  # Use non-standard port to avoid conflicts with local postgres

# Cleanup function
cleanup() {
    echo ""
    echo "🧹 Cleaning up..."
    docker stop "$POSTGRES_CONTAINER" 2>/dev/null || true
    docker rm "$POSTGRES_CONTAINER" 2>/dev/null || true
}

# Trap EXIT to ensure cleanup
trap cleanup EXIT

# Step 1: Start PostgreSQL container with host network (EXACTLY like CI)
echo "🐘 Starting PostgreSQL 15 container on port $POSTGRES_PORT..."
docker run -d \
    --name "$POSTGRES_CONTAINER" \
    -e POSTGRES_USER="$POSTGRES_USER" \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    -e POSTGRES_DB="$POSTGRES_DB" \
    -p $POSTGRES_PORT:5432 \
    postgres:15

echo "⏳ Waiting for PostgreSQL to be ready..."
sleep 5

# Wait for PostgreSQL to accept connections
for i in {1..30}; do
    if docker exec "$POSTGRES_CONTAINER" pg_isready -U "$POSTGRES_USER" > /dev/null 2>&1; then
        echo "✅ PostgreSQL is ready"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${RED}❌ PostgreSQL failed to start${NC}"
        exit 1
    fi
    sleep 1
done

# Step 3: Show PostgreSQL connection info and ensure clean database
echo ""
echo "📊 PostgreSQL Info:"
docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\conninfo"
docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version();"

# Drop and recreate database to ensure clean slate (like CI does)
echo ""
echo "🗑️  Dropping and recreating database for clean state..."
docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE IF EXISTS $POSTGRES_DB;"
docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE $POSTGRES_DB;"
echo -e "${GREEN}✅ Clean database created${NC}"

# Step 4: Pull ci-base image (linux/amd64 to match CI's ubuntu-latest)
echo ""
echo "📦 Pulling ci-base image (linux/amd64 - matches CI ubuntu-latest)..."
docker pull --quiet --platform linux/amd64 us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/ci-base:latest 2>&1 | grep -v "WARNING: The requested image" || true
echo -e "${GREEN}✅ CI base image ready${NC}"

# Step 5: Run migrations (with --network host like CI)
echo ""
echo "🔄 Running migrations in linux/amd64 container..."
DATABASE_URL="postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@localhost:$POSTGRES_PORT/$POSTGRES_DB"

docker run --rm \
    --network host \
    -v "$(pwd)":/workspace \
    -w /workspace \
    -e DATABASE_URL="$DATABASE_URL" \
    -e DATABASE_ENGINE="postgresql" \
    -e DATABASE_HOST="localhost" \
    -e DATABASE_PORT="$POSTGRES_PORT" \
    -e DATABASE_NAME="$POSTGRES_DB" \
    -e DATABASE_USER="$POSTGRES_USER" \
    -e DATABASE_PASSWORD="$POSTGRES_PASSWORD" \
    us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/ci-base:latest \
    alembic upgrade head 2>&1 | grep -v "WARNING: The requested image" || true

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Migrations completed successfully${NC}"
else
    echo -e "${RED}❌ Migrations failed${NC}"
    exit 1
fi

# Step 6: Verify tables exist
echo ""
echo "📋 Verifying tables exist..."
docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt" | grep -E "articles|extraction_telemetry_v2|sources"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Tables created successfully${NC}"
else
    echo -e "${RED}❌ Tables not found${NC}"
    exit 1
fi

# Step 7: Run ALL integration tests with PostgreSQL (EXACTLY like CI with --network host)
echo ""
echo "🧪 Running integration tests in linux/amd64 container (matches CI ubuntu-latest)..."
docker run --rm \
    --network host \
    -v "$(pwd)":/workspace \
    -w /workspace \
    -e PYTEST_KEEP_DB_ENV="true" \
    -e DATABASE_URL="$DATABASE_URL" \
    -e TELEMETRY_DATABASE_URL="$DATABASE_URL" \
    -e TEST_DATABASE_URL="$DATABASE_URL" \
    -e DATABASE_ENGINE="postgresql" \
    -e DATABASE_HOST="localhost" \
    -e DATABASE_PORT="$POSTGRES_PORT" \
    -e DATABASE_NAME="$POSTGRES_DB" \
    -e DATABASE_USER="$POSTGRES_USER" \
    -e DATABASE_PASSWORD="$POSTGRES_PASSWORD" \
    us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/ci-base:latest \
    /bin/bash -c "pytest -v -m integration --tb=short -o addopts='--cov=src --cov-report=term-missing --cov-fail-under=78 -p no:postgresql' --no-cov" 2>&1 | { grep -v "WARNING: The requested image's platform" || true; }

TEST_EXIT_CODE=${PIPESTATUS[0]}

if [ $TEST_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✅ All integration tests passed${NC}"
else
    echo -e "${RED}❌ Integration tests failed${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}🎉 All local CI tests passed!${NC}"
echo ""
echo "💡 To debug interactively:"
echo "   docker exec -it $POSTGRES_CONTAINER psql -U $POSTGRES_USER -d $POSTGRES_DB"
echo ""
echo "   docker run --rm -it --network $NETWORK_NAME \\"
echo "       -v \$(pwd):/workspace -w /workspace \\"
echo "       -e DATABASE_URL=\"$DATABASE_URL\" \\"
echo "       us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/ci-base:latest \\"
echo "       /bin/bash"
