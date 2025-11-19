# Work Queue Refactoring - Complete Testing Suite

## Overview

This major refactoring adds centralized work queue coordination for domain-aware extraction. Before production deployment, comprehensive local testing is required to verify:

1. **No duplicate articles** - FOR UPDATE SKIP LOCKED working correctly
2. **Domain coordination** - Multiple workers don't hit same domains
3. **Database writes** - All articles, entities, labels written correctly
4. **Fallback mode** - System works without work queue if needed
5. **Performance** - Throughput improvement vs baseline

## Testing Infrastructure

### Files Created

```
scripts/
├── test-work-queue-all.sh       # Master test runner (runs all tests)
├── test-work-queue-smoke.sh     # Fast validation (2 min)
├── test-work-queue-full.sh      # Complete E2E test (10 min)
├── TESTING_GUIDE.md             # Comprehensive documentation
└── TEST_QUICK_REF.md            # Quick reference card

docker-compose.yml               # Updated with work-queue service
```

### Docker Services

- **postgres** - PostgreSQL 16 database
- **api** - FastAPI backend (for migrations)
- **work-queue** - Centralized coordinator (NEW)
- **crawler** - Extraction workers

## Quick Start

### Option 1: Run Everything (Recommended)

```bash
./scripts/test-work-queue-all.sh
```

This runs all tests in sequence and reports overall pass/fail.

### Option 2: Individual Tests

```bash
# Fast validation (2 minutes)
./scripts/test-work-queue-smoke.sh

# Complete test (10 minutes)
./scripts/test-work-queue-full.sh
```

## Test Coverage

### Smoke Test (Phase 1)
- ✓ Docker images build
- ✓ Services start successfully
- ✓ Work queue health endpoint responds
- ✓ Stats endpoint returns valid JSON
- ✓ Work request endpoint accepts requests
- ✓ Unit tests pass (11 tests)

### Full Integration Test (Phase 2-6)

**Phase 1: Environment Setup**
- Build all Docker images
- Start PostgreSQL
- Run Alembic migrations
- Seed 200 test candidate_links across 10 domains

**Phase 2: Work Queue Service Tests**
- Start work queue service
- Verify health endpoint
- Verify stats endpoint
- Test work request with mock worker
- Validate JSON responses

**Phase 3: Extraction WITH Work Queue**
- Run 3 parallel workers with USE_WORK_QUEUE=true
- Monitor for 90 seconds
- Verify articles extracted
- Check for duplicates (must be 0)
- Verify domain distribution

**Phase 4: Fallback Mode Test**
- Stop work queue service
- Run extraction with USE_WORK_QUEUE=false
- Verify fallback still works
- Confirm articles extracted

**Phase 5: Database Write Verification**
- Verify all tables exist
- Check article data integrity
- Verify foreign key relationships
- Confirm no orphaned records

**Phase 6: Performance Comparison**
- Compare work queue vs fallback throughput
- Calculate articles per minute
- Report efficiency gains

## Expected Results

### Smoke Test Output
```
✓ Health check passed
✓ Stats endpoint working
✓ Work request endpoint working
✓ Unit tests passed
Smoke Test Passed! ✓
```

### Full Integration Test Output
```
Phase 1: Environment Setup
✓ Images built
✓ PostgreSQL ready
✓ Migrations applied
✓ Test data seeded

Phase 2: Work Queue Service Tests
✓ Work queue service ready
✓ /health endpoint working
✓ /stats endpoint working
✓ Work request successful

Phase 3: Extraction with Work Queue (Enabled)
✓ Extraction with work queue successful
✓ No duplicate articles (FOR UPDATE SKIP LOCKED working)
✓ Good domain diversity (8 domains)

Phase 4: Fallback Test (Work Queue Disabled)
✓ Fallback mode working

Phase 5: Database Write Verification
✓ All required tables exist
✓ Article data integrity verified
✓ No orphaned articles (foreign keys intact)

Phase 6: Performance Comparison
Work Queue:  ~20 articles/min
Fallback:    ~13 articles/min

All Tests Passed! ✓
Ready for production deployment!
```

## Success Criteria

Before deploying to production:

- [ ] `test-work-queue-all.sh` exits with code 0
- [ ] No duplicate articles created (duplicate check = 0)
- [ ] Domain diversity ≥ 5 unique domains extracted
- [ ] Fallback mode functional
- [ ] All database writes verified
- [ ] Foreign key relationships intact
- [ ] No errors in service logs
- [ ] Unit tests: 11/11 passed
- [ ] Integration tests: 8/8 passed

## Troubleshooting

### Common Issues

**1. Port conflicts**
```bash
# Check what's using ports
lsof -i :5432  # PostgreSQL
lsof -i :8081  # Work queue

# Kill conflicting processes or change ports in docker-compose.yml
```

**2. Out of memory**
```bash
# Increase Docker memory to 4GB minimum
# Docker Desktop → Settings → Resources → Memory
```

**3. Stale containers**
```bash
# Clean slate
docker-compose down -v
docker system prune -f
docker volume prune -f
```

**4. Image build failures**
```bash
# Check Dockerfile.crawler exists
ls -l Dockerfile.crawler

# Rebuild with no cache
docker-compose build --no-cache work-queue
```

### Getting Help

1. Check logs: `docker-compose logs work-queue`
2. Review full guide: `scripts/TESTING_GUIDE.md`
3. Check quick reference: `scripts/TEST_QUICK_REF.md`
4. Inspect database: `docker exec -it mizzou-postgres psql -U mizzou_user -d mizzou`

## Next Steps After Testing

### 1. All Tests Pass ✓

```bash
# Commit test infrastructure
git add scripts/test-work-queue-*.sh scripts/TESTING_GUIDE.md scripts/TEST_QUICK_REF.md docker-compose.yml
git commit -m "Add comprehensive local testing suite for work queue refactoring"
git push origin copilot/implement-centralized-work-queue

# Update PR with test results
# Include output showing all phases passed
```

### 2. Deploy to Staging

```bash
# Deploy work queue service
kubectl apply -f k8s/work-queue-deployment.yaml -n staging

# Update Argo workflow with WORK_QUEUE_URL
kubectl apply -f k8s/argo/base-pipeline-workflow.yaml -n staging

# Build and deploy updated crawler
./scripts/deploy-services.sh copilot/implement-centralized-work-queue ci
```

### 3. Monitor Staging (1 hour)

```bash
# Check throughput
kubectl exec -n staging deploy/mizzou-api -- python -c "
from src.models.database import DatabaseManager
from sqlalchemy import text
db = DatabaseManager()
with db.get_session() as session:
    result = session.execute(text('''
        SELECT COUNT(*) FROM articles 
        WHERE extracted_at >= NOW() - INTERVAL '1 hour'
    ''')).scalar()
    print(f'Articles last hour: {result}')
"

# Check for duplicates
kubectl exec -n staging deploy/mizzou-api -- python -c "
from src.models.database import DatabaseManager
from sqlalchemy import text
db = DatabaseManager()
with db.get_session() as session:
    result = session.execute(text('''
        SELECT COUNT(*) FROM (
            SELECT candidate_link_id, COUNT(*) 
            FROM articles 
            GROUP BY candidate_link_id 
            HAVING COUNT(*) > 1
        ) dupes
    ''')).scalar()
    print(f'Duplicate articles: {result}')
"

# Monitor queue stats
watch -n 10 'kubectl exec -n staging deploy/work-queue -- curl -s localhost:8080/stats | jq'
```

### 4. Deploy to Production

After staging validation:

1. Merge PR to main
2. Deploy work queue: `kubectl apply -f k8s/work-queue-deployment.yaml -n production`
3. Deploy crawler: `./scripts/deploy-services.sh main ci`
4. Monitor for 2 hours with rollback plan ready

## Performance Expectations

### Local Test (Docker)
- **Throughput:** ~20 articles/minute with 3 workers
- **Domains:** 5-8 unique domains per run
- **Duplicates:** 0 (always)

### Staging Environment
- **Throughput:** 50-80 articles/hour with 3 workers
- **Domains:** 15+ unique domains
- **Paused links:** <20% (vs 75% before)

### Production Target
- **Throughput:** 100+ articles/hour with 6 workers
- **Batch efficiency:** 30+ articles per batch (vs 3 before)
- **Paused links:** <10%
- **Domain diversity:** >80% of available domains

## Summary

This testing suite provides **comprehensive validation** before production deployment:

✓ **Fast feedback** - Smoke test in 2 minutes  
✓ **Complete coverage** - All components tested  
✓ **Real database** - PostgreSQL with actual writes  
✓ **Multi-worker** - Parallel execution verified  
✓ **Fallback safety** - System works without queue  
✓ **Data integrity** - All writes validated  
✓ **Performance metrics** - Throughput measured  

**Run `./scripts/test-work-queue-all.sh` before every deployment!**
