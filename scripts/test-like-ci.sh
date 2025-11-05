#!/bin/bash
set -e

# Test script that mimics CI environment using Docker
# Run this before pushing to catch CI failures locally
#
# This script:
# 1. Starts a PostgreSQL 15 container with CI-like configuration
# 2. Runs migrations
# 3. Runs integration tests with PostgreSQL
# 4. Cleans up

echo "🧪 Running tests like CI (using Docker + PostgreSQL 15)..."
echo ""

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    if [ -f "/Applications/Docker.app/Contents/Resources/bin/docker" ]; then
        export DOCKER="/Applications/Docker.app/Contents/Resources/bin/docker"
    else
        echo "❌ Docker not found. Please install Docker Desktop."
        exit 1
    fi
else
    export DOCKER="docker"
fi

# Check if Docker is running
if ! $DOCKER info &> /dev/null; then
    echo "❌ Docker is not running. Please start Docker Desktop."
    exit 1
fi

# Configuration (matching CI)
POSTGRES_USER="postgres"
POSTGRES_PASSWORD="postgres"
POSTGRES_DB="test_db"
CONTAINER_NAME="pre-push-test-postgres"
POSTGRES_PORT="5434"  # Use different port to avoid conflicts

# Cleanup function
cleanup() {
    echo ""
    echo "🧹 Cleaning up Docker container..."
    $DOCKER stop "$CONTAINER_NAME" 2>/dev/null || true
    $DOCKER rm "$CONTAINER_NAME" 2>/dev/null || true
}

# Trap EXIT to ensure cleanup
trap cleanup EXIT

# Start PostgreSQL container
echo "🐘 Starting PostgreSQL 15 container..."
$DOCKER run -d \
    --name "$CONTAINER_NAME" \
    -e POSTGRES_USER="$POSTGRES_USER" \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    -e POSTGRES_DB="$POSTGRES_DB" \
    -p $POSTGRES_PORT:5432 \
    postgres:15 > /dev/null

# Wait for PostgreSQL to be ready
echo "⏳ Waiting for PostgreSQL to be ready..."
for i in {1..30}; do
    if $DOCKER exec "$CONTAINER_NAME" pg_isready -U "$POSTGRES_USER" > /dev/null 2>&1; then
        echo "✅ PostgreSQL is ready"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "❌ PostgreSQL failed to start"
        exit 1
    fi
    sleep 1
done

# Give PostgreSQL a moment to fully initialize
sleep 2

# Use host.docker.internal for Docker on Mac to access the PostgreSQL container
# On Linux, use --network host instead
DATABASE_URL="postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@localhost:$POSTGRES_PORT/$POSTGRES_DB"

# Pull the CI base image (same as CI uses)
echo ""
echo "🐳 Pulling CI base image..."
$DOCKER pull us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/ci-base:latest

if [ $? -ne 0 ]; then
    echo "❌ Failed to pull CI base image. Check your GCP authentication."
    exit 1
fi

# Run migrations in CI container (matching CI exactly)
echo ""
echo "📦 Running Alembic migrations in CI container..."
$DOCKER run --rm \
    --network host \
    -v "$(pwd):/workspace" \
    -w /workspace \
    -e DATABASE_URL="$DATABASE_URL" \
    us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/ci-base:latest \
    alembic upgrade head

if [ $? -eq 0 ]; then
    echo "✅ Migrations completed"
else
    echo "❌ Migrations failed"
    exit 1
fi

# Run PostgreSQL integration tests in CI container (matching CI exactly)
echo ""
echo "🧪 Running PostgreSQL integration tests in CI container..."
$DOCKER run --rm \
    --network host \
    -v "$(pwd):/workspace" \
    -w /workspace \
    -e DATABASE_URL="$DATABASE_URL" \
    -e TELEMETRY_DATABASE_URL="$DATABASE_URL" \
    -e TEST_DATABASE_URL="$DATABASE_URL" \
    us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/ci-base:latest \
    pytest tests/ -m integration -v --maxfail=3 --tb=short

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ All tests passed! Safe to push to CI."
else
    echo ""
    echo "❌ Tests failed. Fix issues before pushing."
    exit 1
fi
