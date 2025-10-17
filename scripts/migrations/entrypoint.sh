#!/bin/bash
# Entrypoint script for running Alembic migrations
# This script is designed to run in a Kubernetes Job with Cloud SQL credentials

set -euo pipefail

echo "========================================="
echo "Alembic Migration Entrypoint"
echo "========================================="
echo "Starting at: $(date -Iseconds)"

# Validate required environment variables
required_vars=(
    "USE_CLOUD_SQL_CONNECTOR"
    "CLOUD_SQL_INSTANCE"
    "DATABASE_USER"
    "DATABASE_PASSWORD"
    "DATABASE_NAME"
)

echo "Checking required environment variables..."
for var in "${required_vars[@]}"; do
    if [ -z "${!var:-}" ]; then
        echo "ERROR: Required environment variable $var is not set"
        exit 1
    fi
    echo "  ✓ $var is set"
done

# Change to application root
cd /app

# Verify alembic files are present
echo ""
echo "Verifying migration files..."
if [ ! -f "alembic.ini" ]; then
    echo "ERROR: alembic.ini not found in /app"
    exit 1
fi
echo "  ✓ alembic.ini found"

if [ ! -d "alembic" ]; then
    echo "ERROR: alembic/ directory not found in /app"
    exit 1
fi
echo "  ✓ alembic/ directory found"

if [ ! -d "alembic/versions" ]; then
    echo "ERROR: alembic/versions directory not found"
    exit 1
fi
echo "  ✓ alembic/versions/ directory found"

# Count migration files
migration_count=$(find alembic/versions -name "*.py" -not -name "__init__.py" | wc -l)
echo "  ✓ Found $migration_count migration files"

# Check current database version
echo ""
echo "Checking current database version..."
alembic -c alembic.ini current || {
    echo "WARNING: Could not get current version (database may be new)"
}

# Run migrations
echo ""
echo "Running migrations..."
echo "Command: alembic -c alembic.ini upgrade head"
alembic -c alembic.ini upgrade head

# Verify migrations succeeded
echo ""
echo "Verifying migrations succeeded..."
alembic -c alembic.ini current

echo ""
echo "========================================="
echo "Migration completed successfully!"
echo "Finished at: $(date -Iseconds)"
echo "========================================="
exit 0
