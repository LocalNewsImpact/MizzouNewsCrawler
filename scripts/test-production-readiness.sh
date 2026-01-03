#!/bin/bash
# Run Docker-based production readiness tests
# These tests run in actual containers to verify production environment setup

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

echo "🐳 Docker-Based Production Readiness Tests"
echo "=========================================="
echo ""
echo "These tests run in actual Docker containers to verify:"
echo "  ✓ Container imports and PYTHONPATH configuration"
echo "  ✓ ChromeDriver initialization and browser automation"
echo "  ✓ Production entrypoints work correctly"
echo "  ✓ Extraction method logic and ordering"
echo ""

# Build Docker images
echo "🔨 Building Docker images..."
docker-compose --profile base build base
docker-compose build crawler processor
echo ""

# Run the tests
echo "🧪 Running production readiness tests..."
echo ""

pytest tests/docker/test_production_readiness.py \
    -v \
    --tb=short \
    --color=yes \
    "$@"

exit_code=$?

echo ""
if [ $exit_code -eq 0 ]; then
    echo "✅ All production readiness tests passed!"
else
    echo "❌ Production readiness tests failed"
    echo ""
    echo "These failures indicate the code will NOT work in production."
    echo "Fix these issues before deploying."
fi

exit $exit_code
