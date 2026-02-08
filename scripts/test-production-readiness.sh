#!/bin/bash
# Run Docker-based production readiness tests
# These tests run in actual containers to verify production environment setup

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Skip Docker tests on unsupported architectures (Chrome amd64 only)
# These tests require actual Docker containers - they can't run on arm64 Mac
ARCH=$(uname -m)
if [ "$ARCH" != "x86_64" ] && [ "$ARCH" != "amd64" ]; then
    echo "⏭️  Skipping Docker tests on $ARCH"
    echo "    Docker/Chrome tests require amd64 - will run on GitHub CI"
    exit 0
fi
