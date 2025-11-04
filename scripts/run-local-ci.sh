#!/bin/bash
#
# Run local CI tests that match GitHub Actions CI environment
#
# Usage:
#   ./scripts/run-local-ci.sh              # Run all test suites
#   ./scripts/run-local-ci.sh unit         # Run only unit tests
#   ./scripts/run-local-ci.sh integration  # Run only integration tests
#   ./scripts/run-local-ci.sh postgres     # Run only postgres tests
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

cd "$PROJECT_ROOT"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Local CI Test Runner${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if PostgreSQL is running
check_postgres() {
    echo -e "${YELLOW}Checking PostgreSQL...${NC}"
    if ! psql -h localhost -U "$USER" -d postgres -c "SELECT 1" > /dev/null 2>&1; then
        echo -e "${RED}✗ PostgreSQL is not running or not accessible${NC}"
        echo -e "${YELLOW}  Start PostgreSQL with: brew services start postgresql@15${NC}"
        return 1
    fi
    echo -e "${GREEN}✓ PostgreSQL is running${NC}"
    
    # Check if test database exists
    if ! psql -h localhost -U "$USER" -d postgres -c "SELECT 1 FROM pg_database WHERE datname='news_crawler_test'" | grep -q 1; then
        echo -e "${YELLOW}Creating test database...${NC}"
        createdb news_crawler_test
    fi
    echo -e "${GREEN}✓ Test database exists${NC}"
    echo ""
}

# Run unit tests (no database)
run_unit_tests() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Running Unit Tests${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
    
    pytest \
        -v \
        --no-cov \
        -m "not integration and not postgres and not slow" \
        --maxfail=5 \
        tests/
}

# Run integration tests (SQLite)
run_integration_tests() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Running Integration Tests (SQLite)${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
    
    # Clear environment variables that might interfere
    unset DATABASE_URL
    unset TEST_DATABASE_URL
    unset TELEMETRY_DATABASE_URL
    
    pytest \
        -v \
        --no-cov \
        -m "not postgres" \
        --maxfail=5 \
        tests/
}

# Run PostgreSQL integration tests
run_postgres_tests() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Running PostgreSQL Integration Tests${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
    
    if ! check_postgres; then
        return 1
    fi
    
    # Set environment variables for PostgreSQL tests
    export TEST_DATABASE_URL="postgresql://$USER@localhost/news_crawler_test"
    export DATABASE_URL="postgresql://$USER@localhost/news_crawler_test"
    export TELEMETRY_DATABASE_URL="postgresql://$USER@localhost/news_crawler_test"
    export PYTEST_KEEP_DB_ENV="true"
    
    # Run migrations
    echo -e "${YELLOW}Running database migrations...${NC}"
    alembic upgrade head
    echo -e "${GREEN}✓ Migrations complete${NC}"
    echo ""
    
    pytest \
        -v \
        --no-cov \
        -m "integration" \
        --maxfail=5 \
        tests/
}

# Run full CI test suite with coverage
run_full_ci() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Running Full CI Test Suite${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
    
    if ! check_postgres; then
        return 1
    fi
    
    # Set environment variables for PostgreSQL tests
    export TEST_DATABASE_URL="postgresql://$USER@localhost/news_crawler_test"
    export DATABASE_URL="postgresql://$USER@localhost/news_crawler_test"
    export TELEMETRY_DATABASE_URL="postgresql://$USER@localhost/news_crawler_test"
    export PYTEST_KEEP_DB_ENV="true"
    
    # Run migrations
    echo -e "${YELLOW}Running database migrations...${NC}"
    alembic upgrade head
    echo -e "${GREEN}✓ Migrations complete${NC}"
    echo ""
    
    pytest \
        --cov=src \
        --cov-report=xml \
        --cov-report=html \
        --cov-report=term-missing \
        --cov-fail-under=78 \
        -v \
        tests/
}

# Main script logic
case "${1:-all}" in
    unit)
        run_unit_tests
        ;;
    integration)
        run_integration_tests
        ;;
    postgres)
        run_postgres_tests
        ;;
    all|full)
        echo -e "${YELLOW}Running all test suites...${NC}"
        echo ""
        
        run_unit_tests
        echo ""
        
        run_integration_tests
        echo ""
        
        run_postgres_tests
        echo ""
        
        echo -e "${GREEN}========================================${NC}"
        echo -e "${GREEN}All test suites passed! ✓${NC}"
        echo -e "${GREEN}========================================${NC}"
        ;;
    ci)
        run_full_ci
        ;;
    *)
        echo "Usage: $0 {unit|integration|postgres|all|ci}"
        echo ""
        echo "  unit        - Run unit tests (no database)"
        echo "  integration - Run integration tests with SQLite"
        echo "  postgres    - Run PostgreSQL integration tests"
        echo "  all         - Run all test suites sequentially"
        echo "  ci          - Run full CI suite with coverage"
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}✓ Tests completed successfully${NC}"
