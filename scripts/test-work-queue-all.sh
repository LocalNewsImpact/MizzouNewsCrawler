#!/bin/bash
# Master test runner - runs all work queue tests in sequence
# Use this before submitting PR or deploying to production

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${BLUE}╔════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Work Queue Master Test Suite                ║${NC}"
echo -e "${BLUE}║   Complete validation before deployment       ║${NC}"
echo -e "${BLUE}╔════════════════════════════════════════════════╗${NC}"
echo ""

# Track results
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

run_test() {
    local test_name=$1
    local test_script=$2
    
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
    echo -e "${BLUE}Running: $test_name${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
    echo ""
    
    TESTS_RUN=$((TESTS_RUN + 1))
    
    if "$test_script"; then
        TESTS_PASSED=$((TESTS_PASSED + 1))
        echo -e "${GREEN}✓ $test_name PASSED${NC}"
        return 0
    else
        TESTS_FAILED=$((TESTS_FAILED + 1))
        echo -e "${RED}✗ $test_name FAILED${NC}"
        return 1
    fi
}

# Run all tests
run_test "Smoke Test" "${SCRIPT_DIR}/test-work-queue-smoke.sh" || true
run_test "Full Integration Test" "${SCRIPT_DIR}/test-work-queue-full.sh" || true

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo -e "${BLUE}Test Suite Complete${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo ""
echo "Results:"
echo "  Tests run:    $TESTS_RUN"
echo -e "  ${GREEN}Tests passed: $TESTS_PASSED${NC}"
if [ $TESTS_FAILED -gt 0 ]; then
    echo -e "  ${RED}Tests failed: $TESTS_FAILED${NC}"
else
    echo "  Tests failed: $TESTS_FAILED"
fi
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}╔════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║   ALL TESTS PASSED ✓                           ║${NC}"
    echo -e "${GREEN}║   Ready for production deployment!            ║${NC}"
    echo -e "${GREEN}╔════════════════════════════════════════════════╗${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Review test output above"
    echo "  2. Commit changes: git add . && git commit -m 'Work queue tests passed'"
    echo "  3. Push to PR: git push origin copilot/implement-centralized-work-queue"
    echo "  4. Deploy to staging: kubectl apply -f k8s/work-queue-deployment.yaml -n staging"
    echo ""
    exit 0
else
    echo -e "${RED}╔════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║   TESTS FAILED ✗                               ║${NC}"
    echo -e "${RED}║   Fix issues before deployment                 ║${NC}"
    echo -e "${RED}╔════════════════════════════════════════════════╗${NC}"
    echo ""
    echo "Review logs above and fix failing tests."
    echo "See scripts/TESTING_GUIDE.md for troubleshooting."
    echo ""
    exit 1
fi
