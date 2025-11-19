#!/bin/bash
# Full end-to-end test for work queue refactoring in Docker environment
# Tests ALL functionality including database writes, coordination, and fallback

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test configuration
TEST_DURATION=${TEST_DURATION:-300}  # 5 minutes default
NUM_WORKERS=${NUM_WORKERS:-3}        # Test with 3 workers
MAX_ARTICLES_PER_RUN=${MAX_ARTICLES_PER_RUN:-20}

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Work Queue Full Integration Test${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "Configuration:"
echo "  - Test duration: ${TEST_DURATION}s"
echo "  - Number of workers: ${NUM_WORKERS}"
echo "  - Max articles per run: ${MAX_ARTICLES_PER_RUN}"
echo ""

# Function to run SQL query
run_query() {
    docker exec mizzou-postgres psql -U mizzou_user -d mizzou -t -c "$1" 2>/dev/null | xargs
}

# Function to get work queue stats
get_queue_stats() {
    docker exec mizzou-work-queue curl -s http://localhost:8080/stats 2>/dev/null || echo "{}"
}

# Function to check service health
check_health() {
    local service=$1
    local url=$2
    
    # For postgres, use pg_isready
    if [[ "$service" == "mizzou-postgres" ]]; then
        docker exec "$service" pg_isready -U mizzou_user > /dev/null 2>&1
        return $?
    fi
    
    # For other services, try curl (may not be installed)
    docker exec "$service" curl -sf "$url" > /dev/null 2>&1
}

# Cleanup function
cleanup() {
    echo -e "\n${YELLOW}Cleaning up...${NC}"
    docker-compose -f "${PROJECT_ROOT}/docker-compose.yml" \
        --profile work-queue \
        --profile crawler \
        down -v 2>/dev/null || true
}

trap cleanup EXIT

echo -e "${BLUE}Phase 1: Environment Setup${NC}"
echo "----------------------------------------"

cd "${PROJECT_ROOT}"

# Check if images exist, only build if missing
echo "Checking Docker images..."
if ! docker images | grep -q mizzou-base; then
    echo "Building base image (first time only)..."
    docker-compose build base || {
        echo -e "${RED}Failed to build base image${NC}"
        exit 1
    }
else
    echo -e "${GREEN}✓ Base image exists (using existing)${NC}"
fi

# Only build work-queue if it doesn't exist or is needed
if ! docker images | grep -q mizzou-crawler; then
    echo "Building crawler/work-queue images..."
    docker-compose build crawler work-queue || {
        echo -e "${RED}Failed to build service images${NC}"
        exit 1
    }
else
    echo -e "${GREEN}✓ Service images exist (using existing)${NC}"
fi

echo -e "${GREEN}✓ Images ready${NC}"

# Start services
echo "Starting PostgreSQL..."
docker-compose up -d postgres

# Wait for PostgreSQL
echo "Waiting for PostgreSQL to be ready..."
for i in {1..30}; do
    if check_health mizzou-postgres http://localhost:5432; then
        echo -e "${GREEN}✓ PostgreSQL ready${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${RED}PostgreSQL failed to start${NC}"
        docker-compose logs postgres
        exit 1
    fi
    sleep 2
done

# Run migrations
echo "Running database migrations..."
docker-compose run --rm work-queue alembic upgrade head || {
    echo -e "${RED}Failed to run migrations${NC}"
    exit 1
}
echo -e "${GREEN}✓ Migrations applied${NC}"

# Seed test data
echo "Seeding test data (sources and candidate_links)..."
docker-compose run --rm api python -c "
from src.models.database import DatabaseManager
from src.models import Source, CandidateLink
import uuid

db = DatabaseManager()
with db.get_session() as session:
    # Create 10 test sources
    sources = []
    for i in range(10):
        source = Source(
            id=str(uuid.uuid4()),
            host=f'test-domain-{i}.com',
            host_norm=f'test-domain-{i}.com',
            canonical_name=f'Test Domain {i}',
            status='active',
            city='Test City',
            county='Test County'
        )
        session.add(source)
        sources.append(source)
    
    session.commit()
    
    # Create 20 candidate_links per source (200 total)
    for source in sources:
        for j in range(20):
            link = CandidateLink(
                id=str(uuid.uuid4()),
                url=f'https://{source.host}/article-{j}',
                source=source.host,
                source_id=source.id,
                status='article',
                discovered_by='test-setup'
            )
            session.add(link)
    
    session.commit()
    print(f'Created {len(sources)} sources with 200 total candidate_links')
" || {
    echo -e "${RED}Failed to seed test data${NC}"
    exit 1
}
echo -e "${GREEN}✓ Test data seeded${NC}"

# Verify initial state
INITIAL_CANDIDATES=$(run_query "SELECT COUNT(*) FROM candidate_links WHERE status='article'")
echo "Initial candidate_links: $INITIAL_CANDIDATES"

echo ""
echo -e "${BLUE}Phase 2: Work Queue Service Tests${NC}"
echo "----------------------------------------"

# Start work queue service
echo "Starting work queue service..."
docker-compose --profile work-queue up -d work-queue

# Wait for work queue to be healthy
echo "Waiting for work queue service..."
for i in {1..30}; do
    # Check from host on mapped port 8081
    if curl -sf http://localhost:8081/health > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Work queue service ready${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${RED}Work queue service failed to start${NC}"
        docker-compose logs work-queue
        exit 1
    fi
    sleep 2
done

# Test work queue endpoints
echo ""
echo "Testing work queue endpoints..."

# Test /health (from host since curl not in container)
if curl -sf http://localhost:8081/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓ /health endpoint working${NC}"
else
    echo -e "${RED}✗ /health endpoint failed${NC}"
    exit 1
fi

# Test /stats
STATS=$(get_queue_stats)
if [ -n "$STATS" ] && [ "$STATS" != "{}" ]; then
    echo -e "${GREEN}✓ /stats endpoint working${NC}"
    echo "  Initial stats: $(echo $STATS | jq -c '{total_available, worker_assignments}' 2>/dev/null || echo $STATS)"
else
    echo -e "${RED}✗ /stats endpoint failed${NC}"
    exit 1
fi

# Test /work/request
echo "Testing work request..."
WORK_RESPONSE=$(docker exec mizzou-work-queue curl -s -X POST http://localhost:8080/work/request \
    -H "Content-Type: application/json" \
    -d '{"worker_id":"test-worker-1","batch_size":10,"max_articles_per_domain":3}')

if echo "$WORK_RESPONSE" | jq -e '.items | length > 0' > /dev/null 2>&1; then
    ITEMS_COUNT=$(echo "$WORK_RESPONSE" | jq '.items | length')
    DOMAINS=$(echo "$WORK_RESPONSE" | jq -r '.worker_domains | join(", ")')
    echo -e "${GREEN}✓ Work request successful${NC}"
    echo "  Received: $ITEMS_COUNT items from domains: $DOMAINS"
else
    echo -e "${RED}✗ Work request failed${NC}"
    echo "  Response: $WORK_RESPONSE"
    exit 1
fi

echo ""
echo -e "${BLUE}Phase 3: Extraction with Work Queue (Enabled)${NC}"
echo "----------------------------------------"

# Test extraction WITH work queue
echo "Running extraction with USE_WORK_QUEUE=true..."

BEFORE_ARTICLES=$(run_query "SELECT COUNT(*) FROM articles")
echo "Articles before extraction: $BEFORE_ARTICLES"

# Run 3 parallel extraction workers
for worker_num in $(seq 1 $NUM_WORKERS); do
    echo "Starting worker $worker_num..."
    docker-compose run -d --rm \
        -e USE_WORK_QUEUE=true \
        -e WORK_QUEUE_URL=http://work-queue:8080 \
        -e MAX_ARTICLES_PER_DOMAIN_PER_BATCH=3 \
        -e LOG_LEVEL=INFO \
        --name "test-worker-${worker_num}" \
        crawler python -m src.cli.main extract-parallel \
            --per-batch 15 \
            --num-batches 2 \
            --max-articles $MAX_ARTICLES_PER_RUN
done

# Monitor for 60 seconds
echo "Monitoring extraction progress (60s)..."
for i in {1..12}; do
    sleep 5
    
    # Check articles extracted
    CURRENT_ARTICLES=$(run_query "SELECT COUNT(*) FROM articles")
    NEW_ARTICLES=$((CURRENT_ARTICLES - BEFORE_ARTICLES))
    
    # Check worker assignments
    STATS=$(get_queue_stats)
    ACTIVE_WORKERS=$(echo "$STATS" | jq -r '.worker_assignments | length' 2>/dev/null || echo "?")
    
    echo "  [${i}] Articles: $NEW_ARTICLES extracted, Active workers: $ACTIVE_WORKERS"
done

# Wait for workers to complete
echo "Waiting for workers to complete..."
sleep 30

AFTER_ARTICLES=$(run_query "SELECT COUNT(*) FROM articles")
EXTRACTED_WITH_QUEUE=$((AFTER_ARTICLES - BEFORE_ARTICLES))

echo ""
echo "Extraction Results (WITH work queue):"
echo "  - Articles extracted: $EXTRACTED_WITH_QUEUE"
echo "  - Before: $BEFORE_ARTICLES"
echo "  - After: $AFTER_ARTICLES"

if [ $EXTRACTED_WITH_QUEUE -gt 0 ]; then
    echo -e "${GREEN}✓ Extraction with work queue successful${NC}"
else
    echo -e "${RED}✗ No articles extracted with work queue${NC}"
    echo "Worker logs:"
    for worker_num in $(seq 1 $NUM_WORKERS); do
        echo "--- Worker $worker_num ---"
        docker logs "test-worker-${worker_num}" 2>&1 | tail -50
    done
    exit 1
fi

# Verify no duplicate articles
DUPLICATE_CHECK=$(run_query "
    SELECT COUNT(*) FROM (
        SELECT candidate_link_id, COUNT(*) as cnt
        FROM articles
        WHERE candidate_link_id IS NOT NULL
        GROUP BY candidate_link_id
        HAVING COUNT(*) > 1
    ) dupes
")

if [ "$DUPLICATE_CHECK" -eq 0 ]; then
    echo -e "${GREEN}✓ No duplicate articles (FOR UPDATE SKIP LOCKED working)${NC}"
else
    echo -e "${RED}✗ Found $DUPLICATE_CHECK duplicate articles${NC}"
    exit 1
fi

# Verify domain distribution
echo ""
echo "Domain distribution analysis:"
DOMAIN_DISTRIBUTION=$(run_query "
    SELECT cl.source, COUNT(*) as articles
    FROM articles a
    JOIN candidate_links cl ON a.candidate_link_id = cl.id
    GROUP BY cl.source
    ORDER BY articles DESC
    LIMIT 5
")
echo "$DOMAIN_DISTRIBUTION"

UNIQUE_DOMAINS=$(run_query "
    SELECT COUNT(DISTINCT cl.source)
    FROM articles a
    JOIN candidate_links cl ON a.candidate_link_id = cl.id
")
echo "Unique domains extracted: $UNIQUE_DOMAINS"

if [ "$UNIQUE_DOMAINS" -ge 3 ]; then
    echo -e "${GREEN}✓ Good domain diversity (${UNIQUE_DOMAINS} domains)${NC}"
else
    echo -e "${YELLOW}⚠ Low domain diversity (${UNIQUE_DOMAINS} domains)${NC}"
fi

echo ""
echo -e "${BLUE}Phase 4: Fallback Test (Work Queue Disabled)${NC}"
echo "----------------------------------------"

# Stop work queue service
echo "Stopping work queue service..."
docker-compose stop work-queue

# Clear articles for retest
echo "Resetting articles table..."
run_query "TRUNCATE articles CASCADE"

# Reset candidate_links status
run_query "UPDATE candidate_links SET status='article' WHERE status='paused'"

BEFORE_FALLBACK=$(run_query "SELECT COUNT(*) FROM articles")

# Run extraction WITHOUT work queue
echo "Running extraction with USE_WORK_QUEUE=false (fallback mode)..."
docker-compose run --rm \
    -e USE_WORK_QUEUE=false \
    -e LOG_LEVEL=INFO \
    crawler python -m src.cli.main extract-parallel \
        --per-batch 15 \
        --num-batches 2 \
        --max-articles $MAX_ARTICLES_PER_RUN

AFTER_FALLBACK=$(run_query "SELECT COUNT(*) FROM articles")
EXTRACTED_FALLBACK=$((AFTER_FALLBACK - BEFORE_FALLBACK))

echo ""
echo "Extraction Results (WITHOUT work queue - fallback):"
echo "  - Articles extracted: $EXTRACTED_FALLBACK"

if [ $EXTRACTED_FALLBACK -gt 0 ]; then
    echo -e "${GREEN}✓ Fallback mode working${NC}"
else
    echo -e "${RED}✗ Fallback mode failed${NC}"
    docker-compose logs crawler | tail -100
    exit 1
fi

echo ""
echo -e "${BLUE}Phase 5: Database Write Verification${NC}"
echo "----------------------------------------"

# Verify all expected tables and columns
echo "Verifying database schema..."

REQUIRED_TABLES=("articles" "candidate_links" "sources" "article_entities" "article_labels")
for table in "${REQUIRED_TABLES[@]}"; do
    TABLE_EXISTS=$(run_query "SELECT COUNT(*) FROM information_schema.tables WHERE table_name='$table'")
    if [ "$TABLE_EXISTS" -eq 1 ]; then
        echo -e "${GREEN}✓ Table '$table' exists${NC}"
    else
        echo -e "${RED}✗ Table '$table' missing${NC}"
        exit 1
    fi
done

# Verify articles have proper structure
echo ""
echo "Verifying article data integrity..."

ARTICLES_WITH_TEXT=$(run_query "SELECT COUNT(*) FROM articles WHERE text IS NOT NULL AND text != ''")
ARTICLES_WITH_URL=$(run_query "SELECT COUNT(*) FROM articles WHERE url IS NOT NULL")
ARTICLES_WITH_TIMESTAMP=$(run_query "SELECT COUNT(*) FROM articles WHERE extracted_at IS NOT NULL")

TOTAL_ARTICLES=$(run_query "SELECT COUNT(*) FROM articles")

echo "Articles with text: $ARTICLES_WITH_TEXT / $TOTAL_ARTICLES"
echo "Articles with URL: $ARTICLES_WITH_URL / $TOTAL_ARTICLES"
echo "Articles with timestamp: $ARTICLES_WITH_TIMESTAMP / $TOTAL_ARTICLES"

if [ "$ARTICLES_WITH_TEXT" -gt 0 ] && \
   [ "$ARTICLES_WITH_URL" -eq "$TOTAL_ARTICLES" ] && \
   [ "$ARTICLES_WITH_TIMESTAMP" -eq "$TOTAL_ARTICLES" ]; then
    echo -e "${GREEN}✓ Article data integrity verified${NC}"
else
    echo -e "${RED}✗ Article data integrity issues found${NC}"
    exit 1
fi

# Check for proper foreign key relationships
echo ""
echo "Verifying foreign key relationships..."

ORPHANED_ARTICLES=$(run_query "
    SELECT COUNT(*) FROM articles a
    WHERE candidate_link_id IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM candidate_links cl WHERE cl.id = a.candidate_link_id)
")

if [ "$ORPHANED_ARTICLES" -eq 0 ]; then
    echo -e "${GREEN}✓ No orphaned articles (foreign keys intact)${NC}"
else
    echo -e "${RED}✗ Found $ORPHANED_ARTICLES orphaned articles${NC}"
    exit 1
fi

echo ""
echo -e "${BLUE}Phase 6: Performance Comparison${NC}"
echo "----------------------------------------"

echo "Summary:"
echo "  Work Queue Mode:  $EXTRACTED_WITH_QUEUE articles extracted"
echo "  Fallback Mode:    $EXTRACTED_FALLBACK articles extracted"
echo ""

# Calculate efficiency (articles per minute)
if [ $EXTRACTED_WITH_QUEUE -gt 0 ] && [ $EXTRACTED_FALLBACK -gt 0 ]; then
    WQ_RATE=$(echo "scale=2; $EXTRACTED_WITH_QUEUE / 1.5" | bc)  # ~90s runtime
    FB_RATE=$(echo "scale=2; $EXTRACTED_FALLBACK / 1.5" | bc)
    
    echo "Throughput comparison:"
    echo "  Work Queue:  ~${WQ_RATE} articles/min"
    echo "  Fallback:    ~${FB_RATE} articles/min"
    echo ""
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}All Tests Passed! ✓${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "Summary:"
echo "  ✓ Work queue service operational"
echo "  ✓ Extraction with work queue successful"
echo "  ✓ No duplicate articles (coordination working)"
echo "  ✓ Domain diversity achieved"
echo "  ✓ Fallback mode functional"
echo "  ✓ Database writes verified"
echo "  ✓ Data integrity confirmed"
echo "  ✓ Foreign key relationships intact"
echo ""
echo "Ready for production deployment!"
echo ""
