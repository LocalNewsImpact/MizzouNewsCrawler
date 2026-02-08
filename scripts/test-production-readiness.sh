#!/bin/bash
# Run Docker-based production readiness tests
# These tests run in actual containers to verify production environment setup

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# Detect architecture
ARCH=$(uname -m)

echo "🐳 Docker-Based Production Readiness Tests"
echo "=========================================="
echo ""
echo "These tests run in actual Docker containers to verify:"
echo "  ✓ Container imports and PYTHONPATH configuration"
echo "  ✓ Production entrypoints work correctly"
if [ "$ARCH" = "x86_64" ] || [ "$ARCH" = "amd64" ]; then
    echo "  ✓ ChromeDriver initialization and browser automation"
else
    echo "  ⊘ ChromeDriver tests skipped on $ARCH (Chrome amd64 only)"
fi
echo ""

# Use existing Docker images (don't rebuild)
echo "✓ Using existing Docker images"
echo "  (use NO_DOCKER_BUILD=0 to rebuild if needed)"
echo ""

# Run the tests
echo "🧪 Running production readiness tests..."
echo ""

# Build pytest args
PYTEST_ARGS=(
    "tests/docker/"
    "-v"
    "--tb=short"
    "--color=yes"
    "--no-cov"
    "-m" "docker"
)

# Skip Chrome tests on arm64
if [ "$ARCH" != "x86_64" ] && [ "$ARCH" != "amd64" ]; then
    echo "⚠️  Skipping Chrome-specific tests on $ARCH"
    PYTEST_ARGS+=("-m" "not skip_chrome_arm64")
fi

# Add any user-provided args
PYTEST_ARGS+=("$@")

pytest "${PYTEST_ARGS[@]}"

exit_code=$?

echo ""
if [ $exit_code -eq 0 ]; then
    echo "✅ All Docker tests passed!"
else
    echo "❌ Docker tests failed"
fi

exit $exit_code
