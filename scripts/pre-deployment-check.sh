#!/bin/bash
# Pre-deployment checklist validator
# Ensures all requirements met before production deployment

set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Pre-Deployment Checklist Validator          ║${NC}"
echo -e "${BLUE}╔════════════════════════════════════════════════╗${NC}"
echo ""

PASS=0
FAIL=0
WARN=0

check() {
    local name=$1
    local command=$2
    local required=${3:-true}
    
    echo -n "Checking: $name... "
    
    if eval "$command" > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
        PASS=$((PASS + 1))
        return 0
    else
        if [ "$required" = "true" ]; then
            echo -e "${RED}✗ REQUIRED${NC}"
            FAIL=$((FAIL + 1))
        else
            echo -e "${YELLOW}⚠ WARNING${NC}"
            WARN=$((WARN + 1))
        fi
        return 1
    fi
}

echo "Repository Checks:"
check "Git branch is work queue branch" \
    "[ \$(git branch --show-current) = 'copilot/implement-centralized-work-queue' ]"

check "No uncommitted changes" \
    "[ -z \"\$(git status --porcelain)\" ]" \
    false

check "All test scripts exist" \
    "[ -f scripts/test-work-queue-all.sh ] && [ -f scripts/test-work-queue-smoke.sh ] && [ -f scripts/test-work-queue-full.sh ]"

echo ""
echo "Code Checks:"
check "Work queue service exists" \
    "[ -f src/services/work_queue.py ]"

check "Kubernetes deployment exists" \
    "[ -f k8s/work-queue-deployment.yaml ]"

check "Unit tests exist" \
    "[ -f tests/services/test_work_queue.py ]"

check "Integration tests exist" \
    "[ -f tests/integration/test_work_queue_integration.py ]"

check "Extraction command updated" \
    "grep -q 'USE_WORK_QUEUE' src/cli/commands/extraction.py"

echo ""
echo "Docker Checks:"
check "Docker is running" \
    "docker ps > /dev/null 2>&1"

check "docker-compose.yml has work-queue service" \
    "grep -q 'work-queue:' docker-compose.yml"

check "Base image exists or can be built" \
    "docker images | grep -q mizzou-base || docker-compose build base" \
    false

echo ""
echo "Testing Checks:"
if [ -f .test_results ]; then
    check "Smoke test passed" \
        "grep -q 'smoke.*PASSED' .test_results"
    
    check "Full integration test passed" \
        "grep -q 'full.*PASSED' .test_results"
else
    echo -e "${YELLOW}⚠ No test results found (run ./scripts/test-work-queue-all.sh)${NC}"
    WARN=$((WARN + 1))
fi

echo ""
echo "Documentation Checks:"
check "Testing guide exists" \
    "[ -f scripts/TESTING_GUIDE.md ]"

check "Quick reference exists" \
    "[ -f scripts/TEST_QUICK_REF.md ]"

check "README mentions work queue" \
    "grep -qi 'work.queue' README.md" \
    false

echo ""
echo "╔════════════════════════════════════════════════╗"
echo "║   Results                                      ║"
echo "╔════════════════════════════════════════════════╗"
echo ""
echo -e "  ${GREEN}Passed:   $PASS${NC}"
echo -e "  ${RED}Failed:   $FAIL${NC}"
echo -e "  ${YELLOW}Warnings: $WARN${NC}"
echo ""

if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}✓ Pre-deployment checks passed!${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Run full test suite: ./scripts/test-work-queue-all.sh"
    echo "  2. Review test output for any issues"
    echo "  3. Deploy to staging environment"
    echo "  4. Monitor staging for 1 hour"
    echo "  5. Deploy to production"
    echo ""
    exit 0
else
    echo -e "${RED}✗ Pre-deployment checks failed!${NC}"
    echo ""
    echo "Fix the failed checks above before deploying."
    echo "See scripts/TESTING_GUIDE.md for help."
    echo ""
    exit 1
fi
