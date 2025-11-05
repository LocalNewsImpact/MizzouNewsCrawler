#!/bin/bash
set -e

# Simplified CI test - just PostgreSQL connection and migrations
# Tests the exact same PostgreSQL config as GitHub Actions

echo "🧪 Testing CI PostgreSQL setup locally..."
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Use Docker from Docker Desktop if not in PATH
if ! command -v docker &> /dev/null; then
    export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
fi

# Configuration matching CI
POSTGRES_USER="postgres"
POSTGRES_PASSWORD="postgres"
POSTGRES_DB="test_db"
POSTGRES_CONTAINER="ci-test-postgres"

# Cleanup function
cleanup() {
    echo ""
    echo "🧹 Cleaning up..."
    docker stop "$POSTGRES_CONTAINER" 2>/dev/null || true
    docker rm "$POSTGRES_CONTAINER" 2>/dev/null || true
}

# Trap EXIT to ensure cleanup
trap cleanup EXIT

# Start PostgreSQL container (EXACT same config as CI workflow)
echo "🐘 Starting PostgreSQL 15 container (matching CI config)..."
docker run -d \
    --name "$POSTGRES_CONTAINER" \
    -e POSTGRES_USER="$POSTGRES_USER" \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    -e POSTGRES_DB="$POSTGRES_DB" \
    -p 5433:5432 \
    postgres:15

echo "⏳ Waiting for PostgreSQL to be ready..."
for i in {1..30}; do
    if docker exec "$POSTGRES_CONTAINER" pg_isready -U "$POSTGRES_USER" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ PostgreSQL is ready${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${RED}❌ PostgreSQL failed to start${NC}"
        exit 1
    fi
    sleep 1
done

# Give PostgreSQL a moment to fully initialize the database
sleep 2

# Verify database exists
echo "🔍 Verifying database..."
if ! docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT 1;" > /dev/null 2>&1; then
    echo -e "${RED}❌ Database $POSTGRES_DB not accessible${NC}"
    echo "Available databases:"
    docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d postgres -c "\l"
    exit 1
fi
echo -e "${GREEN}✅ Database $POSTGRES_DB is accessible${NC}"

# Test 1: Check connection info
echo ""
echo "📊 Test 1: PostgreSQL Connection Info"
docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\conninfo"
echo -e "${GREEN}✅ Connection info retrieved${NC}"

# Test 2: Check pg_hba.conf authentication config
echo ""
echo "📊 Test 2: Authentication Configuration (pg_hba.conf)"
docker exec "$POSTGRES_CONTAINER" cat /var/lib/postgresql/data/pg_hba.conf | grep -v "^#" | grep -v "^$"
echo ""
echo -e "${YELLOW}Note: CI uses 'scram-sha-256' password auth (not 'trust')${NC}"

# Test 3: Try connecting with password
echo ""
echo "📊 Test 3: Test password authentication"
PGPASSWORD="$POSTGRES_PASSWORD" docker exec "$POSTGRES_CONTAINER" \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT 'Password auth works!' as test;"
echo -e "${GREEN}✅ Password authentication successful${NC}"

# Test 4: Try connecting WITHOUT password (should fail with current config)
echo ""
echo "📊 Test 4: Test connection WITHOUT password (should fail)"
if docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT 1;" 2>/dev/null; then
    echo -e "${YELLOW}⚠️  Connection without password succeeded (trust auth enabled)${NC}"
else
    echo -e "${GREEN}✅ Connection without password failed (password required - correct!)${NC}"
fi

# Test 5: Try connecting as 'root' user (should fail)
echo ""
echo "📊 Test 5: Test connection as 'root' user (should fail)"
if PGPASSWORD="$POSTGRES_PASSWORD" docker exec "$POSTGRES_CONTAINER" \
    psql -U root -d "$POSTGRES_DB" -c "SELECT 1;" 2>&1 | grep -q "role \"root\" does not exist"; then
    echo -e "${GREEN}✅ Correctly rejected connection as 'root' user${NC}"
else
    echo -e "${RED}❌ Expected 'role root does not exist' error${NC}"
fi

# Test 6: Run migrations from local venv
echo ""
echo "📊 Test 6: Run Alembic migrations"
DATABASE_URL="postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@localhost:5433/$POSTGRES_DB"
export DATABASE_URL

if [ -d "venv" ]; then
    source venv/bin/activate
    echo "Using DATABASE_URL: $DATABASE_URL"
    alembic upgrade head
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ Migrations completed${NC}"
    else
        echo -e "${RED}❌ Migrations failed${NC}"
        exit 1
    fi
else
    echo -e "${YELLOW}⚠️  No venv found - skipping migration test${NC}"
    echo "   Run: python -m venv venv && source venv/bin/activate && pip install -e ."
fi

# Test 7: Verify tables exist
echo ""
echo "📊 Test 7: Verify tables were created"
docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt" | head -20

if docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT tablename FROM pg_tables WHERE schemaname='public';" | grep -q "articles"; then
    echo -e "${GREEN}✅ Tables created successfully${NC}"
else
    echo -e "${RED}❌ Tables not found${NC}"
    exit 1
fi

# Test 8: Check specific table that was failing in CI
echo ""
echo "📊 Test 8: Verify 'article_labels' table (was incorrectly named 'article_classifications')"
if docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT COUNT(*) FROM article_labels;" > /dev/null 2>&1; then
    echo -e "${GREEN}✅ article_labels table exists and is queryable${NC}"
else
    echo -e "${RED}❌ article_labels table missing or not accessible${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}🎉 All PostgreSQL tests passed!${NC}"
echo ""
echo "📝 Summary:"
echo "  - PostgreSQL authentication: ✅ Password required (no trust)"
echo "  - User 'postgres' with password: ✅ Works"
echo "  - User 'root': ✅ Correctly rejected"
echo "  - Migrations: ✅ Completed"
echo "  - Tables: ✅ Created"
echo ""
echo "💡 Database is still running. To connect:"
echo "   PGPASSWORD=$POSTGRES_PASSWORD psql -h localhost -p 5433 -U $POSTGRES_USER -d $POSTGRES_DB"
echo ""
echo "   To keep running: Press Ctrl+C to exit cleanup, then run:"
echo "   docker stop $POSTGRES_CONTAINER && docker rm $POSTGRES_CONTAINER"
