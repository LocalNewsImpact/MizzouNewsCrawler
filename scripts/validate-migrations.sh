#!/bin/bash
# Script to validate Alembic migrations before deployment
# This script can be run in Cloud Build or locally to catch migration issues early

set -e  # Exit on error

echo "=================================="
echo "Alembic Migration Validation"
echo "=================================="

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Track overall status
VALIDATION_FAILED=0

# Function to print colored output
print_status() {
    local status=$1
    local message=$2
    
    if [ "$status" == "OK" ]; then
        echo -e "${GREEN}✓${NC} $message"
    elif [ "$status" == "FAIL" ]; then
        echo -e "${RED}✗${NC} $message"
        VALIDATION_FAILED=1
    elif [ "$status" == "WARN" ]; then
        echo -e "${YELLOW}⚠${NC} $message"
    else
        echo "  $message"
    fi
}

echo ""
echo "1. Checking Alembic configuration..."

# Check that alembic.ini exists
if [ -f "alembic.ini" ]; then
    print_status "OK" "alembic.ini found"
else
    print_status "FAIL" "alembic.ini not found"
fi

# Check that alembic/env.py exists
if [ -f "alembic/env.py" ]; then
    print_status "OK" "alembic/env.py found"
else
    print_status "FAIL" "alembic/env.py not found"
fi

echo ""
echo "2. Validating migration history..."

# Check migration history
if alembic history > /dev/null 2>&1; then
    print_status "OK" "Migration history is valid"
    
    # Count migrations
    MIGRATION_COUNT=$(alembic history | grep -c "^[a-f0-9]" || echo "0")
    print_status "INFO" "Found $MIGRATION_COUNT migrations"
else
    print_status "FAIL" "Migration history validation failed"
fi

echo ""
echo "3. Checking for migration conflicts..."

# Check for branch conflicts
if alembic branches 2>&1 | grep -q "No conflicts"; then
    print_status "OK" "No migration conflicts detected"
elif [ -z "$(alembic branches 2>&1)" ]; then
    print_status "OK" "No migration branches"
else
    print_status "FAIL" "Migration conflicts detected"
    alembic branches
fi

echo ""
echo "4. Testing migration on temporary SQLite database..."

# Create temporary database and test migration
TEMP_DIR=$(mktemp -d)
TEMP_DB="$TEMP_DIR/validation.db"

export DATABASE_URL="sqlite:///$TEMP_DB"
export USE_CLOUD_SQL_CONNECTOR="false"

echo "   Using temporary database: $TEMP_DB"

# Try to run migrations
if alembic upgrade head 2>&1 | tee "$TEMP_DIR/migration.log"; then
    print_status "OK" "Migration to head succeeded"
    
    # Check that alembic_version table exists
    if sqlite3 "$TEMP_DB" "SELECT version_num FROM alembic_version;" > /dev/null 2>&1; then
        VERSION=$(sqlite3 "$TEMP_DB" "SELECT version_num FROM alembic_version;")
        print_status "OK" "Database at version: $VERSION"
    else
        print_status "WARN" "Could not read alembic_version table"
    fi
else
    print_status "FAIL" "Migration failed - check logs"
    cat "$TEMP_DIR/migration.log"
fi

# Test downgrade
echo ""
echo "5. Testing migration downgrade..."

if alembic downgrade -1 2>&1 | tee "$TEMP_DIR/downgrade.log"; then
    print_status "OK" "Downgrade succeeded"
else
    print_status "FAIL" "Downgrade failed"
    cat "$TEMP_DIR/downgrade.log"
fi

# Test upgrade back to head
echo ""
echo "6. Testing migration re-upgrade..."

if alembic upgrade head 2>&1 | tee "$TEMP_DIR/reupgrade.log"; then
    print_status "OK" "Re-upgrade succeeded"
else
    print_status "FAIL" "Re-upgrade failed"
    cat "$TEMP_DIR/reupgrade.log"
fi

# Cleanup
rm -rf "$TEMP_DIR"

echo ""
echo "7. Checking for common migration issues..."

# Check for CREATE TABLE without IF NOT EXISTS
MIGRATIONS_DIR="alembic/versions"
if grep -r "create_table" "$MIGRATIONS_DIR" --include="*.py" | grep -v "if_not_exists" > /dev/null; then
    print_status "WARN" "Some CREATE TABLE statements may not use IF NOT EXISTS"
    print_status "INFO" "This could cause issues with duplicate table creation"
else
    print_status "OK" "No obvious CREATE TABLE issues found"
fi

# Check for missing downgrade implementations
MISSING_DOWNGRADE=0
for migration in "$MIGRATIONS_DIR"/*.py; do
    if ! grep -q "def downgrade" "$migration"; then
        print_status "WARN" "Migration $(basename $migration) may be missing downgrade()"
        MISSING_DOWNGRADE=1
    fi
done

if [ $MISSING_DOWNGRADE -eq 0 ]; then
    print_status "OK" "All migrations have downgrade() functions"
fi

echo ""
echo "=================================="
if [ $VALIDATION_FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ Migration validation PASSED${NC}"
    echo "=================================="
    exit 0
else
    echo -e "${RED}✗ Migration validation FAILED${NC}"
    echo "=================================="
    exit 1
fi
