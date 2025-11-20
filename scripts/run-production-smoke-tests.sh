#!/bin/bash
#
# Run E2E smoke tests against production environment
#
# Usage:
#   ./scripts/run-production-smoke-tests.sh [test_module]
#
# Examples:
#   ./scripts/run-production-smoke-tests.sh                          # Run all smoke tests
#   ./scripts/run-production-smoke-tests.sh TestSectionURLExtraction # Run specific test class
#   ./scripts/run-production-smoke-tests.sh --verbose                # Run with verbose output

set -e

NAMESPACE="production"
POD_LABEL="app=mizzou-processor"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}🧪 Running production smoke tests...${NC}"
echo ""

# Get pod name
POD_NAME=$(kubectl get pods -n "$NAMESPACE" -l "$POD_LABEL" -o jsonpath='{.items[0].metadata.name}')

if [ -z "$POD_NAME" ]; then
    echo -e "${RED}❌ No processor pod found in $NAMESPACE namespace${NC}"
    exit 1
fi

echo "Using pod: $POD_NAME"
echo ""

# Build pytest command
PYTEST_CMD="pytest tests/e2e/test_production_smoke.py"

# Add test filter if provided
if [ -n "$1" ]; then
    if [ "$1" == "--verbose" ] || [ "$1" == "-v" ]; then
        PYTEST_CMD="$PYTEST_CMD -v"
    else
        PYTEST_CMD="$PYTEST_CMD -k $1 -v"
    fi
else
    PYTEST_CMD="$PYTEST_CMD -v"
fi

# Add color and output formatting
PYTEST_CMD="$PYTEST_CMD --color=yes --tb=short"

echo -e "${YELLOW}Running: $PYTEST_CMD${NC}"
echo ""

# Run tests in pod
if kubectl exec -n "$NAMESPACE" "$POD_NAME" -- bash -c "$PYTEST_CMD"; then
    echo ""
    echo -e "${GREEN}✅ All smoke tests passed!${NC}"
    exit 0
else
    EXIT_CODE=$?
    echo ""
    echo -e "${RED}❌ Smoke tests failed with exit code $EXIT_CODE${NC}"
    echo ""
    echo "To debug, connect to the pod:"
    echo "  kubectl exec -it -n $NAMESPACE $POD_NAME -- bash"
    echo ""
    exit $EXIT_CODE
fi
