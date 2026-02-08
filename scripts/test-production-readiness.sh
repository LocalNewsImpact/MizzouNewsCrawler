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

# Build Docker images (skip if NO_DOCKER_BUILD=1)
echo "🔨 Building Docker images..."
if [ "${NO_DOCKER_BUILD:-}" = "1" ] || [ "${SKIP_BUILD:-}" = "1" ]; then
    echo "⚠️  Skipping docker-compose build because NO_DOCKER_BUILD=1 or SKIP_BUILD=1"
else
    docker-compose --profile base build base
    docker-compose build crawler processor
fi
echo ""

# Run the tests
echo "🧪 Running production readiness tests..."
echo ""

# Skip Chrome tests on unsupported architectures (amd64 only)
ARCH=$(uname -m)
if [ "$ARCH" = "x86_64" ] || [ "$ARCH" = "amd64" ]; then
    # Run all Docker tests including Chrome
    pytest tests/docker/ \
        -v \
        --tb=short \
        --color=yes \
        --no-cov \
        -m docker \
        "$@"
else
    # Skip Chrome tests on arm64/aarch64 (Apple Silicon)
    echo "⚠️  Running Docker tests but skipping Chrome-specific tests on $ARCH"
    pytest tests/docker/ \
        -v \
        --tb=short \
        --color=yes \
        --no-cov \
        -m docker \
        -m "not skip_chrome_arm64" \
        "$@"
fi

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
