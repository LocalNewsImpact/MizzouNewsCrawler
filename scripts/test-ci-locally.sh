#!/bin/bash
# Run full CI/CD test suite locally (replicates GitHub Actions environment)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

echo "🚀 Local CI/CD Test Suite"
echo "=========================================="
echo ""
echo "Running the same tests that GitHub Actions runs:"
echo "  ✓ Unit tests (fast, no database)"
echo "  ✓ Integration tests (SQLite in-memory)"
echo "  ✓ PostgreSQL integration tests (Docker container)"
echo ""

# Skip linting if SKIP_LINT=true (already done in pre-push hook)
if [ "${SKIP_LINT:-}" != "true" ]; then
    echo "🔍 Step 1/3: Linting..."
    python -m ruff check .
    python -m black --check src/ tests/ web/
    python -m isort --check-only --profile black src/ tests/ web/
    echo "✅ Linting passed"
    echo ""
fi

# Run unit tests (no database needed)
echo "🧪 Step 2/3: Unit tests..."
pytest tests/ \
    -v \
    --tb=short \
    --color=yes \
    --cov=src \
    --cov-report=term-missing \
    -m "not integration and not postgres and not docker" \
    "$@"

echo "✅ Unit tests passed"
echo ""

# Run integration tests (SQLite)
echo "🧪 Step 3/3: Integration tests (SQLite)..."
pytest tests/ \
    -v \
    --tb=short \
    --color=yes \
    -m "integration and not postgres and not docker" \
    "$@"

echo "✅ Integration tests passed"
echo ""

# PostgreSQL tests (optional - requires Docker)
if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    echo "🐘 Running PostgreSQL integration tests..."
    pytest tests/ \
        -v \
        --tb=short \
        --color=yes \
        -m "postgres and not docker" \
        "$@"
    echo "✅ PostgreSQL tests passed"
else
    echo "⚠️  Skipping PostgreSQL tests (Docker not available)"
fi

echo ""
echo "✅ All CI tests passed!"
