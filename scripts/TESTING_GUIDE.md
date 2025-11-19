# Work Queue Refactoring - Local Testing Guide

This guide covers comprehensive local testing of the work queue refactoring before production deployment.

## Prerequisites

- Docker and Docker Compose installed
- At least 4GB RAM available for Docker
- ~10GB disk space for images and data

## Test Scripts Overview

### 1. Smoke Test (Fast - 2 minutes)
**Purpose:** Quick validation that services start and basic endpoints work

```bash
chmod +x scripts/test-work-queue-smoke.sh
./scripts/test-work-queue-smoke.sh
```

**Tests:**
- ✓ Work queue service starts
- ✓ Health endpoint responds
- ✓ Stats endpoint returns valid JSON
- ✓ Work request endpoint accepts requests
- ✓ Unit tests pass

### 2. Full Integration Test (Comprehensive - 10 minutes)
**Purpose:** Complete end-to-end testing with real extraction and database writes

```bash
chmod +x scripts/test-work-queue-full.sh
./scripts/test-work-queue-full.sh
```

**Tests:**
- ✓ Database migrations apply correctly
- ✓ Test data seeding works
- ✓ Work queue service coordinates multiple workers
- ✓ Domain partitioning prevents overlap
- ✓ Extraction writes articles to database
- ✓ No duplicate articles (FOR UPDATE SKIP LOCKED)
- ✓ Domain diversity achieved across workers
- ✓ Fallback mode works when queue disabled
- ✓ All database writes verified
- ✓ Foreign key relationships intact
- ✓ Data integrity confirmed

## Testing Workflow

### Step 1: Run Smoke Test First

```bash
./scripts/test-work-queue-smoke.sh
```

This catches obvious issues quickly:
- Service startup failures
- Configuration errors
- Import/syntax errors
- Basic API functionality

**If smoke test fails:** Check logs with `docker-compose logs work-queue`

### Step 2: Run Full Integration Test

```bash
./scripts/test-work-queue-full.sh
```

This validates the complete system:
- Multi-worker coordination
- Database writes and reads
- Rate limiting and cooldowns
- Fallback behavior

**Configuration options:**
```bash
# Test with more workers (default: 3)
NUM_WORKERS=6 ./scripts/test-work-queue-full.sh

# Longer test duration (default: 300s)
TEST_DURATION=600 ./scripts/test-work-queue-full.sh

# More articles per run (default: 20)
MAX_ARTICLES_PER_RUN=50 ./scripts/test-work-queue-full.sh
```

### Step 3: Run Existing Test Suites

```bash
# Unit tests
docker-compose run --rm crawler pytest tests/services/test_work_queue.py -v

# Integration tests (requires PostgreSQL)
docker-compose run --rm crawler pytest tests/integration/test_work_queue_integration.py -v -m integration

# All tests
docker-compose run --rm crawler pytest -v
```

## Manual Testing Scenarios

### Scenario 1: Work Queue with Multiple Workers

```bash
# Start services
docker-compose up -d postgres
docker-compose run --rm api alembic upgrade head
docker-compose --profile work-queue up -d work-queue

# Seed data
docker-compose run --rm api python -c "
from src.models.database import DatabaseManager
from src.models import Source, CandidateLink
import uuid

db = DatabaseManager()
with db.get_session() as session:
    # Create 10 sources with 50 articles each
    for i in range(10):
        source = Source(
            id=str(uuid.uuid4()),
            host=f'manual-test-{i}.com',
            host_norm=f'manual-test-{i}.com',
            canonical_name=f'Manual Test {i}',
            status='active'
        )
        session.add(source)
        session.flush()
        
        for j in range(50):
            link = CandidateLink(
                id=str(uuid.uuid4()),
                url=f'https://{source.host}/article-{j}',
                source=source.host,
                source_id=source.id,
                status='article',
                discovered_by='manual'
            )
            session.add(link)
    session.commit()
"

# Run 3 workers in separate terminals
docker-compose run --rm \
    -e USE_WORK_QUEUE=true \
    -e WORK_QUEUE_URL=http://work-queue:8080 \
    crawler python -m src.cli.main extract-parallel --per-batch 20 --num-batches 5

# Monitor queue stats in another terminal
watch -n 2 'docker exec mizzou-work-queue curl -s http://localhost:8080/stats | jq'

# Check results
docker exec mizzou-postgres psql -U mizzou_user -d mizzou -c "
SELECT 
    COUNT(*) as total_articles,
    COUNT(DISTINCT cl.source) as unique_sources,
    MIN(a.extracted_at) as first,
    MAX(a.extracted_at) as last
FROM articles a
JOIN candidate_links cl ON a.candidate_link_id = cl.id;
"
```

### Scenario 2: Test Fallback Mode

```bash
# Stop work queue
docker-compose stop work-queue

# Run extraction (should fallback to direct DB queries)
docker-compose run --rm \
    -e USE_WORK_QUEUE=false \
    crawler python -m src.cli.main extract-parallel --per-batch 20 --num-batches 3

# Should still work without errors
```

### Scenario 3: Test Rate Limiting

```bash
# Monitor domain cooldowns
watch -n 1 'docker exec mizzou-work-queue curl -s http://localhost:8080/stats | jq .domain_cooldowns'

# In another terminal, run extraction
docker-compose run --rm \
    -e USE_WORK_QUEUE=true \
    -e WORK_QUEUE_URL=http://work-queue:8080 \
    -e DOMAIN_COOLDOWN_SECONDS=30 \
    crawler python -m src.cli.main extract-parallel --per-batch 30 --num-batches 10

# You should see domains appear in cooldowns, then clear after timeout
```

## Database Verification Queries

```bash
# Connect to PostgreSQL
docker exec -it mizzou-postgres psql -U mizzou_user -d mizzou

# Check article counts
SELECT COUNT(*) FROM articles;

# Check for duplicates (should return 0)
SELECT candidate_link_id, COUNT(*) 
FROM articles 
GROUP BY candidate_link_id 
HAVING COUNT(*) > 1;

# Domain distribution
SELECT cl.source, COUNT(*) as articles
FROM articles a
JOIN candidate_links cl ON a.candidate_link_id = cl.id
GROUP BY cl.source
ORDER BY articles DESC;

# Recent extraction activity
SELECT 
    DATE_TRUNC('minute', extracted_at) as minute,
    COUNT(*) as articles
FROM articles
WHERE extracted_at >= NOW() - INTERVAL '1 hour'
GROUP BY minute
ORDER BY minute DESC;

# Verify data integrity
SELECT 
    COUNT(*) as total,
    COUNT(text) as has_text,
    COUNT(title) as has_title,
    COUNT(url) as has_url,
    COUNT(extracted_at) as has_timestamp
FROM articles;
```

## Troubleshooting

### Work Queue Service Won't Start

```bash
# Check logs
docker-compose logs work-queue

# Common issues:
# 1. Port conflict - check if port 8081 is in use
lsof -i :8081

# 2. Database connection - verify PostgreSQL is running
docker-compose ps postgres

# 3. Import errors - rebuild image
docker-compose build work-queue
```

### No Articles Being Extracted

```bash
# Check candidate_links exist
docker exec mizzou-postgres psql -U mizzou_user -d mizzou -c "
SELECT status, COUNT(*) FROM candidate_links GROUP BY status;
"

# Check worker logs
docker-compose logs crawler

# Verify work queue is returning work
docker exec mizzou-work-queue curl -s -X POST http://localhost:8080/work/request \
    -H "Content-Type: application/json" \
    -d '{"worker_id":"debug","batch_size":10,"max_articles_per_domain":3}' | jq
```

### Duplicate Articles

```bash
# Check for duplicates
docker exec mizzou-postgres psql -U mizzou_user -d mizzou -c "
SELECT candidate_link_id, COUNT(*) as cnt
FROM articles
GROUP BY candidate_link_id
HAVING COUNT(*) > 1;
"

# If found, this indicates FOR UPDATE SKIP LOCKED not working
# Check PostgreSQL version (must be 9.5+)
docker exec mizzou-postgres psql -U mizzou_user -d mizzou -c "SELECT version();"
```

### Rate Limiting Not Working

```bash
# Check domain cooldowns
docker exec mizzou-work-queue curl -s http://localhost:8080/stats | jq .domain_cooldowns

# Verify DOMAIN_COOLDOWN_SECONDS is set
docker exec mizzou-work-queue env | grep DOMAIN_COOLDOWN

# Check if cooldown time is too short
# Increase to 60s for testing:
docker-compose stop work-queue
docker-compose --profile work-queue up -d work-queue \
    -e DOMAIN_COOLDOWN_SECONDS=60
```

## Success Criteria Checklist

Before deploying to production, verify:

- [ ] Smoke test passes without errors
- [ ] Full integration test passes all phases
- [ ] Unit tests pass (11/11)
- [ ] Integration tests pass (8/8)
- [ ] No duplicate articles created
- [ ] Domain diversity > 50% of available domains
- [ ] Fallback mode works when queue disabled
- [ ] Database writes complete successfully
- [ ] Foreign key relationships intact
- [ ] Worker coordination prevents domain overlap
- [ ] Rate limiting enforced correctly
- [ ] Service restarts without issues
- [ ] Logs show no errors or exceptions

## Performance Baselines

Expected results from full integration test:

| Metric | Target | Notes |
|--------|--------|-------|
| Articles extracted (queue) | 30-60 | 3 workers, 2 batches each |
| Articles extracted (fallback) | 15-30 | Single worker, 2 batches |
| Duplicate rate | 0% | Must be zero |
| Unique domains | ≥5 | At least 50% of test domains |
| Test duration | <10 min | Including setup and teardown |
| Service startup time | <30s | Work queue ready |

## Next Steps After Local Testing

1. **Commit changes:**
   ```bash
   git add .
   git commit -m "Add comprehensive local testing for work queue"
   git push origin copilot/implement-centralized-work-queue
   ```

2. **Update PR with test results:**
   - Paste test output showing all phases passed
   - Include performance metrics
   - Note any issues found and resolved

3. **Deploy to staging:**
   ```bash
   # Deploy work queue service
   kubectl apply -f k8s/work-queue-deployment.yaml -n staging
   
   # Deploy updated crawler
   ./scripts/deploy-services.sh copilot/implement-centralized-work-queue ci
   ```

4. **Monitor staging for 1 hour:**
   - Check throughput improvement
   - Verify no duplicate articles
   - Monitor domain pause rate
   - Check service health

5. **Deploy to production:**
   - Merge PR after approval
   - Deploy during low-traffic window
   - Monitor closely for first 2 hours
   - Have rollback plan ready
