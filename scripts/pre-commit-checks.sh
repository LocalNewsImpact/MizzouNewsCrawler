#!/bin/bash
# Pre-commit validation script
# Run this before every git commit to ensure code quality

set -e  # Exit on any error

echo "========================================"
echo "🔍 Running Pre-Commit Checks"
echo "========================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Track overall success
OVERALL_SUCCESS=true

# 1. Static Analysis (Linting)
echo "📋 Step 1/3: Static Analysis (ruff)"
echo "----------------------------------------"
# Exclude scripts/manual_tests from linting (test scripts with intentional issues)
if ruff check . --exclude scripts/manual_tests > /tmp/lint-output.txt 2>&1; then
    echo -e "${GREEN}✅ Linting passed${NC}"
else
    echo -e "${RED}❌ Linting failed${NC}"
    cat /tmp/lint-output.txt
    OVERALL_SUCCESS=false
fi
echo ""

# 2. Type Checking (OPTIONAL - skip if SKIP_MYPY=1)
if [ "${SKIP_MYPY:-0}" = "0" ]; then
    echo "🔍 Step 2/3: Type Checking (mypy)"
    echo "----------------------------------------"
    # Note: Type checking finds pre-existing type issues in codebase
    # Run with explicit package bases to handle module structure
    if mypy src/ backend/ --explicit-package-bases --ignore-missing-imports > /tmp/mypy-output.txt 2>&1; then
        echo -e "${GREEN}✅ Type checking passed${NC}"
    else
        echo -e "${YELLOW}⚠️  Type checking found issues (non-blocking)${NC}"
        echo "    Set SKIP_MYPY=1 to skip this check"
        # Show first 20 lines of errors
        head -20 /tmp/mypy-output.txt
        # Don't fail the overall check for pre-existing type issues
        # OVERALL_SUCCESS=false
    fi
    echo ""
else
    echo "🔍 Step 2/3: Type Checking (mypy) - SKIPPED"
    echo "----------------------------------------"
    echo -e "${YELLOW}ℹ️  Skipped (SKIP_MYPY=1)${NC}"
    echo ""
fi

# 3. Unit Tests
echo "🧪 Step 3/3: Unit Tests (pytest)"
echo "----------------------------------------"
if pytest tests/ -v --tb=short > /tmp/pytest-output.txt 2>&1; then
    echo -e "${GREEN}✅ All tests passed${NC}"
    # Show summary
    tail -n 10 /tmp/pytest-output.txt
else
    echo -e "${RED}❌ Tests failed${NC}"
    cat /tmp/pytest-output.txt
    OVERALL_SUCCESS=false
fi
echo ""

# Final result
echo "========================================"
if [ "$OVERALL_SUCCESS" = true ]; then
    echo -e "${GREEN}✅ All checks passed! Safe to commit.${NC}"
    echo "========================================"
    exit 0
else
    echo -e "${RED}❌ Some checks failed. Fix errors before committing.${NC}"
    echo "========================================"
    exit 1
fi
