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

# Say which database this is, in the log, in full.
#
# For eight days this job applied migrations to the retired instance and
# reported success. Nothing in the log said which database it had
# reached, so the only way to find out was to query the live one and
# notice it was a revision behind. The name is cheap to print and the
# absence of it cost a week.
echo ""
echo "Connected to:"
echo "  instance: ${CLOUD_SQL_INSTANCE}"
echo "  database: ${DATABASE_NAME}"
echo "  user:     ${DATABASE_USER}"

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
#
# `alembic current` PRINTS the revision. It was the whole of this
# script's verification, and printing is not checking: a run that
# applied nothing, or that stopped short of head, printed a revision and
# exited 0 like any other.
#
# So the revision is compared with the head the image carries. This does
# not catch a migration applied to the wrong database -- that database
# is at head too, and what closes that is every manifest naming its
# instance (k8s/, tests/test_no_retired_db_instance.py). It catches the
# upgrade that quietly did less than it said.
echo ""
echo "Verifying migrations succeeded..."
current_revision=$(alembic -c alembic.ini current 2>/dev/null | tail -1 | awk '{print $1}')
head_revision=$(alembic -c alembic.ini heads 2>/dev/null | tail -1 | awk '{print $1}')

echo "  database is at: ${current_revision:-<none>}"
echo "  image head is:  ${head_revision:-<none>}"

if [ -z "$current_revision" ] || [ -z "$head_revision" ]; then
    echo "ERROR: could not read the revision on both sides"
    echo "  the upgrade reported success, so this is a defect in the check"
    exit 1
fi

if [ "$current_revision" != "$head_revision" ]; then
    echo "ERROR: the database is not at the head this image carries"
    echo "  applied: $current_revision"
    echo "  wanted:  $head_revision"
    echo "  on:      ${CLOUD_SQL_INSTANCE} / ${DATABASE_NAME}"
    exit 1
fi
echo "  ✓ the database is at head"

echo ""
echo "========================================="
echo "Migration completed successfully!"
echo "Finished at: $(date -Iseconds)"
echo "========================================="
exit 0
