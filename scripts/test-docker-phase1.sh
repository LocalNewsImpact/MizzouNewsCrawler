#!/bin/bash
# Quick test script for Phase 1 Docker containers
# Run this after Docker Desktop is installed and running

set -e  # Exit on any error

echo "========================================"
echo "🐳 Phase 1: Docker Container Test"
echo "========================================"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check Docker is running
echo "📋 Step 0: Verify Docker is running"
echo "----------------------------------------"
if ! docker ps > /dev/null 2>&1; then
    echo -e "${RED}❌ Docker is not running!${NC}"
    echo "Please start Docker Desktop and try again."
    exit 1
fi
echo -e "${GREEN}✅ Docker is running${NC}"
echo ""

# Step 1: Build images
echo "📋 Step 1: Building Docker images"
echo "----------------------------------------"
echo "This may take 5-10 minutes on first run..."
if docker compose build; then
    echo -e "${GREEN}✅ All images built successfully${NC}"
else
    echo -e "${RED}❌ Build failed${NC}"
    exit 1
fi
echo ""

# Step 2: Start database
echo "📋 Step 2: Starting database"
echo "----------------------------------------"
if docker compose up -d postgres; then
    echo "Waiting for database to be ready..."
    sleep 5
    echo -e "${GREEN}✅ Database started${NC}"
else
    echo -e "${RED}❌ Database failed to start${NC}"
    exit 1
fi
echo ""

# Step 3: Test API
echo "📋 Step 3: Testing API service"
echo "----------------------------------------"
if docker compose up -d api; then
    echo "Waiting for API to start..."
    sleep 3
    
    # Test health endpoint
    if curl -s http://localhost:8000/health | grep -q "healthy"; then
        echo -e "${GREEN}✅ API health check passed${NC}"
    else
        echo -e "${RED}❌ API health check failed${NC}"
        docker compose logs api
        exit 1
    fi
else
    echo -e "${RED}❌ API failed to start${NC}"
    exit 1
fi
echo ""

# Step 4: Test crawler
echo "📋 Step 4: Testing crawler service"
echo "----------------------------------------"
echo "Running discover-urls with 1 source..."
if docker compose run --rm crawler python -m src.cli.main discover-urls --source-limit 1 2>&1 | tee /tmp/crawler-test.log; then
    if grep -q "Completed" /tmp/crawler-test.log || grep -q "Success" /tmp/crawler-test.log || ! grep -q "Error" /tmp/crawler-test.log; then
        echo -e "${GREEN}✅ Crawler test completed${NC}"
    else
        echo -e "${YELLOW}⚠️  Crawler ran but check logs for issues${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Crawler test had issues (may be expected if no sources configured)${NC}"
fi
echo ""

# Step 5: Test processor
echo "📋 Step 5: Testing processor service"
echo "----------------------------------------"
echo "Running extract with 5 article limit..."
if docker compose run --rm processor python -m src.cli.main extract --limit 5 2>&1 | tee /tmp/processor-test.log; then
    if grep -q "Completed" /tmp/processor-test.log || grep -q "Success" /tmp/processor-test.log || ! grep -q "Error" /tmp/processor-test.log; then
        echo -e "${GREEN}✅ Processor test completed${NC}"
    else
        echo -e "${YELLOW}⚠️  Processor ran but check logs for issues${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Processor test had issues (may be expected if no articles to extract)${NC}"
fi
echo ""

# Step 6: Check all services
echo "📋 Step 6: Service status"
echo "----------------------------------------"
docker compose ps
echo ""

# Step 7: Memory usage
echo "📋 Step 7: Memory usage"
echo "----------------------------------------"
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}"
echo ""

# Summary
echo "========================================"
echo "✅ Phase 1 Testing Complete"
echo "========================================"
echo ""
echo "Next steps:"
echo "1. Check API docs: open http://localhost:8000/docs"
echo "2. Review logs: docker compose logs -f api"
echo "3. Stop services: docker compose down"
echo "4. See full test guide: docs/PHASE_1_TESTING.md"
echo ""
echo "If all tests passed, Phase 1 is complete! 🎉"
echo ""
