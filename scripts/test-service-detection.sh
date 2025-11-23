#!/bin/bash
set -e

# Usage: ./scripts/test-service-detection.sh [base_commit] [head_commit]
# If TEST_FILES env var is set, uses that instead of git diff.

if [ -n "$TEST_FILES" ]; then
    echo "🔍 Testing with provided file list..."
    CHANGED_FILES="$TEST_FILES"
else
    BEFORE="${1:-HEAD~1}"
    AFTER="${2:-HEAD}"

    echo "🔍 Testing Service Detection Logic"
    echo "Range: $BEFORE...$AFTER"
    
    # Get changed files
    CHANGED_FILES=$(git diff --name-only "$BEFORE" "$AFTER")
fi

echo ""

if [ -z "$CHANGED_FILES" ]; then
    echo "No files changed."
    exit 0
fi

echo "📋 Changed files:"
echo "$CHANGED_FILES" | sed 's/^/  /'
echo ""

echo "=== Detection Results ==="

# Initialize flags
BASE=false
ML_BASE=false
PROCESSOR=false
API=false
CRAWLER=false
MIGRATOR=false

# Logic mirrored from .github/workflows/build-and-deploy-services.yml

# Base image
if echo "$CHANGED_FILES" | grep -qE 'Dockerfile\.base|Dockerfile\.ci-base|requirements-base\.txt|requirements-dev\.txt'; then
    BASE=true
    echo "✅ Base: YES"
else
    echo "❌ Base: NO"
fi

# ML Base
if echo "$CHANGED_FILES" | grep -qE 'Dockerfile\.ml-base|requirements-ml\.txt'; then
    ML_BASE=true
    echo "✅ ML Base: YES"
else
    echo "❌ ML Base: NO"
fi

# Processor
if echo "$CHANGED_FILES" | grep -qE 'Dockerfile\.processor|requirements-processor\.txt|src/|pyproject\.toml|alembic/'; then
    PROCESSOR=true
    echo "✅ Processor: YES"
else
    echo "❌ Processor: NO"
fi

# API
if echo "$CHANGED_FILES" | grep -qE 'Dockerfile\.api|requirements-api\.txt|src/|pyproject\.toml|backend/|alembic/'; then
    API=true
    echo "✅ API: YES"
else
    echo "❌ API: NO"
fi

# Crawler
if echo "$CHANGED_FILES" | grep -qE 'Dockerfile\.crawler|requirements-crawler\.txt|src/|pyproject\.toml'; then
    CRAWLER=true
    echo "✅ Crawler: YES"
else
    echo "❌ Crawler: NO"
fi

# Migrator
if echo "$CHANGED_FILES" | grep -qE 'Dockerfile\.migrator|requirements-migrator\.txt|alembic/'; then
    MIGRATOR=true
    echo "✅ Migrator: YES"
else
    echo "❌ Migrator: NO"
fi

echo ""
echo "=== Summary ==="
echo "Services to build:"
[ "$BASE" == "true" ] && echo "- base"
[ "$ML_BASE" == "true" ] && echo "- ml-base"
[ "$PROCESSOR" == "true" ] && echo "- processor"
[ "$API" == "true" ] && echo "- api"
[ "$CRAWLER" == "true" ] && echo "- crawler"
[ "$MIGRATOR" == "true" ] && echo "- migrator"
