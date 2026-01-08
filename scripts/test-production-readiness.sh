#!/bin/bash
# Run Docker-based production readiness tests
# These tests run in actual containers to verify production environment setup

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# Skip on unsupported local architectures (e.g., Apple Silicon arm64).
# Chrome and ChromeDriver packages used in these Dockerfiles are only
# available for amd64; CI will run these tests on amd64 runners.
ARCH=$(uname -m)
if [ "$ARCH" != "x86_64" ] && [ "$ARCH" != "amd64" ]; then
    echo "⚠️  Skipping Docker-based production readiness tests on $ARCH (local machine)."
    echo "    Run these tests on an amd64 machine or let CI run them."
    exit 0
fi

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

pytest tests/docker/ \
    -v \
    --tb=short \
    --color=yes \
    --no-cov \
    -m docker \
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
