#!/bin/bash
# Run Docker-based production readiness tests
# These tests run in actual containers to verify production environment setup

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# Skip on unsupported local architectures (e.g., Apple Silicon arm64) unless
# the user explicitly forces running (NO_DOCKER_BUILD=1) or there are
# prebuilt mizzou images present locally (in which case we'll use them).
ARCH=$(uname -m)
if [ "$ARCH" != "x86_64" ] && [ "$ARCH" != "amd64" ]; then
    if [ "${NO_DOCKER_BUILD:-}" = "1" ]; then
        echo "⚠️  Force-running Docker-based production readiness tests on $ARCH (NO_DOCKER_BUILD=1)."
    else
        # Quick heuristic: if any local image contains 'mizzou', proceed
        if docker image ls --format '{{.Repository}}:{{.Tag}}' | grep -E 'mizzou' >/dev/null 2>&1; then
            echo "⚠️  Found local mizzou images; proceeding to run tests on $ARCH (may require qemu/emulation)."
            # If images are present on non-amd64 hosts, skip trying to rebuild
            SKIP_BUILD=1
        else
            echo "⚠️  Skipping Docker-based production readiness tests on $ARCH (local machine)."
            echo "    Run these tests on an amd64 machine or let CI run them."
            echo "    To force-run locally with existing images, set NO_DOCKER_BUILD=1"
            exit 0
        fi
    fi
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
