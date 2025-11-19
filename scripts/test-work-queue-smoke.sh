#!/bin/bash
# Quick smoke test for work queue - fast validation before full test
# Run this first to catch obvious issues

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}Work Queue Quick Smoke Test${NC}"
echo "=============================="

cd "$(dirname "$0")/.."

# Quick check: are images built?
if ! docker images | grep -q mizzou-base; then
    echo -e "${YELLOW}Base image not found - building (first time only)...${NC}"
    docker-compose build base
else
    echo "Using existing base image ✓"
fi

if ! docker images | grep -q mizzou-crawler; then
    echo -e "${YELLOW}Crawler image not found - building (first time only)...${NC}"
    docker-compose build crawler
else
    echo "Using existing crawler image ✓"
fi

# Start minimal services
echo "Starting PostgreSQL..."
docker-compose up -d postgres
sleep 5

echo "Running migrations..."
docker-compose run --rm api alembic upgrade head

echo "Starting work queue service..."
docker-compose --profile work-queue up -d work-queue
sleep 5

# Test endpoints
echo ""
echo "Testing work queue endpoints..."

# Health check
if docker exec mizzou-work-queue curl -sf http://localhost:8080/health > /dev/null; then
    echo -e "${GREEN}✓ Health check passed${NC}"
else
    echo -e "${RED}✗ Health check failed${NC}"
    docker-compose logs work-queue
    exit 1
fi

# Stats endpoint
STATS=$(docker exec mizzou-work-queue curl -s http://localhost:8080/stats)
if echo "$STATS" | jq -e '.total_available' > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Stats endpoint working${NC}"
    echo "  Stats: $(echo $STATS | jq -c '{total_available, total_paused}')"
else
    echo -e "${RED}✗ Stats endpoint failed${NC}"
    echo "  Response: $STATS"
    exit 1
fi

# Test work request (will be empty without data, but should not error)
WORK=$(docker exec mizzou-work-queue curl -s -X POST http://localhost:8080/work/request \
    -H "Content-Type: application/json" \
    -d '{"worker_id":"test","batch_size":10,"max_articles_per_domain":3}')

if echo "$WORK" | jq -e '.items' > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Work request endpoint working${NC}"
    ITEM_COUNT=$(echo "$WORK" | jq '.items | length')
    echo "  Returned: $ITEM_COUNT items"
else
    echo -e "${RED}✗ Work request endpoint failed${NC}"
    echo "  Response: $WORK"
    docker-compose logs work-queue | tail -30
    exit 1
fi

# Test unit tests
echo ""
echo "Running unit tests..."
if docker-compose run --rm crawler pytest tests/services/test_work_queue.py -v; then
    echo -e "${GREEN}✓ Unit tests passed${NC}"
else
    echo -e "${RED}✗ Unit tests failed${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Smoke Test Passed! ✓${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Ready to run full integration test:"
echo "  ./scripts/test-work-queue-full.sh"
echo ""

# Cleanup
docker-compose --profile work-queue down
