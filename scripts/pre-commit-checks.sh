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
if make lint > /tmp/lint-output.txt 2>&1; then
    echo -e "${GREEN}✅ Linting passed${NC}"
else
    echo -e "${RED}❌ Linting failed${NC}"
    cat /tmp/lint-output.txt
    OVERALL_SUCCESS=false
fi
echo ""

# 2. Type Checking
echo "🔍 Step 2/3: Type Checking (mypy)"
echo "----------------------------------------"
if mypy src/ backend/ --ignore-missing-imports > /tmp/mypy-output.txt 2>&1; then
    echo -e "${GREEN}✅ Type checking passed${NC}"
else
    echo -e "${RED}❌ Type checking failed${NC}"
    cat /tmp/mypy-output.txt
    OVERALL_SUCCESS=false
fi
echo ""

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
