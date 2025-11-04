#!/bin/bash
set -e

# Test script that mimics CI environment
# Run this before pushing to catch CI failures locally

echo "🧪 Running tests like CI..."
echo ""

# Activate virtual environment
source venv/bin/activate

# Set PostgreSQL environment (matching CI)
export DATABASE_URL="postgresql://kiesowd@localhost/news_crawler_test"
export TEST_DATABASE_URL="postgresql://kiesowd@localhost/news_crawler_test"
export TELEMETRY_DATABASE_URL="postgresql://kiesowd@localhost/news_crawler_test"

# Run migrations (like CI does)
echo "📦 Running migrations..."
alembic upgrade head

echo ""
echo "🔬 Running unit tests (no DB)..."
pytest tests/ -m "not integration and not postgres" -v --maxfail=5

echo ""
echo "🐘 Running PostgreSQL integration tests..."
pytest tests/ -m integration -v --maxfail=5

echo ""
echo "✅ All tests passed! Safe to push to CI."
