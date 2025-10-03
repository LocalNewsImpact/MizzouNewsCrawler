# Phase 1: Docker Container Testing Guide

**Status**: Ready for local testing  
**Date**: October 3, 2025  
**Branch**: feature/gcp-kubernetes-deployment

## Prerequisites

### 1. Install Docker Desktop

**Download:**
- macOS: https://www.docker.com/products/docker-desktop/
- Or via Homebrew: `brew install --cask docker`

**Verify installation:**
```bash
docker --version
docker compose version
```

Expected output:
```
Docker version 24.x.x or higher
Docker Compose version v2.x.x or higher
```

### 2. Start Docker Desktop

- Open Docker Desktop application
- Wait for it to say "Docker Desktop is running"
- Check status: `docker ps` should work without errors

---

## Testing Checklist

### ✅ Step 1: Build All Images

```bash
cd /Users/kiesowd/VSCode/NewsCrawler/MizzouNewsCrawler-Scripts

# Build all services
docker compose build

# Expected time: 5-10 minutes (first build)
# Subsequent builds will be faster due to caching
```

**What to watch for:**
- ✅ All three services build successfully (api, crawler, processor)
- ✅ No error messages
- ❌ If errors, check Dockerfile syntax

**Expected output:**
```
[+] Building 300.0s (XX/XX) FINISHED
 => [api internal] load build definition
 => [crawler internal] load build definition
 => [processor internal] load build definition
...
 => => exporting layers
 => => writing image sha256:...
```

---

### ✅ Step 2: Start Database

```bash
# Start just the database first
docker compose up -d postgres

# Check it's running
docker compose ps
```

**Expected output:**
```
NAME                  SERVICE    STATUS      PORTS
mizzou-postgres       postgres   Up 10s      0.0.0.0:5432->5432/tcp
```

**Verify database is ready:**
```bash
docker compose logs postgres | tail -20
```

Look for: `database system is ready to accept connections`

---

### ✅ Step 3: Test API Service

```bash
# Start API service
docker compose up -d api

# Check logs
docker compose logs -f api
```

**Expected log output:**
```
INFO:     Started server process [1]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

**Test the health endpoint:**
```bash
# In another terminal
curl http://localhost:8000/health

# Expected response:
{"status":"healthy"}
```

**Test the API docs:**
```bash
# Open in browser
open http://localhost:8000/docs

# Should show FastAPI Swagger UI
```

**Common issues:**
- Port 8000 already in use: `lsof -ti:8000 | xargs kill -9`
- Database connection failed: Check postgres is running
- Import errors: Check requirements.txt is complete

---

### ✅ Step 4: Test Crawler Service

```bash
# Run crawler in one-off mode (doesn't stay running)
docker compose run --rm crawler python -m src.cli.main discover-urls --source-limit 1

# Expected: Should discover URLs from 1 source
```

**What to check:**
- ✅ Script runs without import errors
- ✅ Can connect to database
- ✅ Outputs discovered URLs
- ✅ Completes successfully

**Check logs for errors:**
```bash
# If it fails, check what went wrong
docker compose logs crawler
```

**Test with actual discovery:**
```bash
# Run full discovery on small batch
docker compose run --rm crawler python -m src.cli.main discover-urls --source-limit 5

# Should process 5 sources and discover URLs
```

---

### ✅ Step 5: Test Processor Service

```bash
# Run extraction on small batch
docker compose run --rm processor python -m src.cli.main extract --limit 5

# Expected: Should extract content from 5 articles
```

**What to check:**
- ✅ Can load spacy models
- ✅ Can connect to database
- ✅ Extracts article content
- ✅ Completes successfully

**Test with verification:**
```bash
# Test URL verification
docker compose run --rm processor python -m src.cli.main verify-urls --limit 10

# Should verify 10 URLs
```

---

### ✅ Step 6: Test Full Stack

```bash
# Start all services together
docker compose up -d

# Check all services are running
docker compose ps
```

**Expected output:**
```
NAME                  SERVICE      STATUS      PORTS
mizzou-api            api          Up          0.0.0.0:8000->8000/tcp
mizzou-postgres       postgres     Up          0.0.0.0:5432->5432/tcp
```

**Test end-to-end flow:**

1. **Add a source via API:**
```bash
curl -X POST http://localhost:8000/sources \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Source",
    "domain": "example.com",
    "seed_urls": ["https://example.com/news"]
  }'
```

2. **Run discovery:**
```bash
docker compose run --rm crawler python -m src.cli.main discover-urls --source-limit 1
```

3. **Run extraction:**
```bash
docker compose run --rm processor python -m src.cli.main extract --limit 5
```

4. **Check results via API:**
```bash
curl http://localhost:8000/articles?limit=5
```

---

### ✅ Step 7: Test Database Persistence

```bash
# Stop all services
docker compose down

# Data should persist (stored in Docker volume)

# Start again
docker compose up -d

# Check data is still there
docker compose exec postgres psql -U postgres -d mizzou -c "SELECT COUNT(*) FROM articles;"
```

**Expected:** Article count should be the same as before

---

### ✅ Step 8: Test Hot Reload (Development)

```bash
# Make a small change to src code
# For example, add a print statement

# Restart API
docker compose restart api

# Check logs to see change took effect
docker compose logs -f api
```

**Note:** Volume mounts in docker-compose.yml enable hot reload for development

---

## Testing with Profiles

Docker Compose profiles let you selectively start services:

```bash
# Start just API + Database (no workers)
docker compose up -d

# Start with crawler worker
docker compose --profile crawler up -d

# Start with processor worker
docker compose --profile processor up -d

# Start with all workers
docker compose --profile crawler --profile processor up -d

# Start with admin tools (Adminer for DB management)
docker compose --profile tools up -d
# Access Adminer at http://localhost:8080
```

---

## Performance Testing

### Memory Usage

```bash
# Check container memory usage
docker stats --no-stream

# Expected (approximate):
# api:       ~200-300 MB
# postgres:  ~50-100 MB
# crawler:   ~300-500 MB (with Playwright)
# processor: ~500-800 MB (with ML models)
```

### Build Cache Testing

```bash
# First build (slow)
time docker compose build

# No-change rebuild (should be fast, ~10 seconds)
time docker compose build

# Change requirements.txt, rebuild (only deps layer rebuilds)
touch requirements.txt
time docker compose build
```

---

## Troubleshooting

### Issue: Build fails with "no space left on device"

```bash
# Clean up Docker resources
docker system prune -a --volumes

# Warning: This removes ALL unused containers, images, and volumes
```

### Issue: Port already in use

```bash
# Find what's using the port
lsof -ti:8000

# Kill the process
lsof -ti:8000 | xargs kill -9

# Or change port in docker-compose.yml:
# ports:
#   - "8001:8000"  # Map to different host port
```

### Issue: Database connection refused

```bash
# Check postgres is running
docker compose ps postgres

# Check postgres logs
docker compose logs postgres

# Restart postgres
docker compose restart postgres

# Wait for "ready to accept connections"
docker compose logs -f postgres
```

### Issue: Import errors in containers

```bash
# Check Python path
docker compose run --rm api python -c "import sys; print(sys.path)"

# Check installed packages
docker compose run --rm api pip list

# Rebuild without cache
docker compose build --no-cache api
```

### Issue: Models not found (processor)

```bash
# Check models directory
docker compose run --rm processor ls -la /app/models

# In production, models will be downloaded from GCS
# For local dev, they're optional (tests will skip if missing)
```

### Issue: Playwright browser not found

```bash
# Rebuild crawler with fresh Playwright install
docker compose build --no-cache crawler

# Or install browsers manually
docker compose run --rm crawler playwright install chromium
```

---

## Validation Checklist

Before marking Phase 1 complete, verify:

- [ ] All three Dockerfiles build successfully
- [ ] docker-compose.yml starts all services
- [ ] API health endpoint responds
- [ ] API docs accessible at /docs
- [ ] Crawler can connect to database
- [ ] Crawler can discover URLs (at least 1 source)
- [ ] Processor can connect to database
- [ ] Processor can extract content (at least 1 article)
- [ ] Database persists data across restarts
- [ ] Volume mounts work (code changes reflected)
- [ ] All services stop cleanly with `docker compose down`
- [ ] Memory usage is reasonable (< 2GB total)
- [ ] No critical errors in logs

---

## Performance Benchmarks

Document baseline performance for comparison:

```bash
# Build time (first run)
time docker compose build
# Record: _____ seconds

# Build time (no changes)
time docker compose build
# Record: _____ seconds

# Startup time
time docker compose up -d
docker compose ps  # Wait until all "Up"
# Record: _____ seconds

# Discovery performance (10 sources)
time docker compose run --rm crawler python -m src.cli.main discover-urls --source-limit 10
# Record: _____ seconds

# Extraction performance (20 articles)
time docker compose run --rm processor python -m src.cli.main extract --limit 20
# Record: _____ seconds

# API response time
time curl http://localhost:8000/health
# Record: _____ ms
```

---

## Clean Up

```bash
# Stop all services
docker compose down

# Stop and remove volumes (deletes data!)
docker compose down -v

# Remove all images
docker compose down --rmi all

# Full cleanup (removes everything)
docker system prune -a --volumes
```

---

## Next Steps

Once Phase 1 testing passes:

1. ✅ Mark Phase 1 complete in BRANCH_README.md
2. ✅ Document any issues found and fixed
3. ✅ Commit test results
4. ✅ Push to remote
5. 🚀 Begin Phase 2: GCP Infrastructure

---

## Test Results Template

Copy this to a file `phase1-test-results.md`:

```markdown
# Phase 1 Test Results

**Date:** October 3, 2025  
**Tester:** [Your Name]  
**Platform:** macOS [version]  
**Docker Version:** [version]

## Build Tests
- [ ] api: SUCCESS / FAIL
- [ ] crawler: SUCCESS / FAIL
- [ ] processor: SUCCESS / FAIL
- Build time (first): _____ seconds
- Build time (cached): _____ seconds

## Service Tests
- [ ] postgres starts: SUCCESS / FAIL
- [ ] api starts: SUCCESS / FAIL
- [ ] Health endpoint works: SUCCESS / FAIL
- [ ] API docs accessible: SUCCESS / FAIL

## Crawler Tests
- [ ] Connects to database: SUCCESS / FAIL
- [ ] Discover URLs (1 source): SUCCESS / FAIL
- [ ] Discover URLs (5 sources): SUCCESS / FAIL
- Discovery time (10 sources): _____ seconds

## Processor Tests
- [ ] Connects to database: SUCCESS / FAIL
- [ ] Extract content (5 articles): SUCCESS / FAIL
- [ ] Verify URLs (10 URLs): SUCCESS / FAIL
- Extraction time (20 articles): _____ seconds

## Integration Tests
- [ ] Full stack starts: SUCCESS / FAIL
- [ ] Database persistence: SUCCESS / FAIL
- [ ] Hot reload works: SUCCESS / FAIL
- [ ] Services stop cleanly: SUCCESS / FAIL

## Performance
- Total memory usage: _____ MB
- API response time: _____ ms
- Container startup time: _____ seconds

## Issues Found
1. [Describe issue 1]
2. [Describe issue 2]

## Issues Fixed
1. [Describe fix 1]
2. [Describe fix 2]

## Conclusion
- [ ] Phase 1 PASSED - Ready for Phase 2
- [ ] Phase 1 FAILED - Issues to resolve
```

---

## Additional Resources

- [Docker Compose docs](https://docs.docker.com/compose/)
- [Docker best practices](https://docs.docker.com/develop/dev-best-practices/)
- [Multi-stage builds](https://docs.docker.com/build/building/multi-stage/)
- [Docker networking](https://docs.docker.com/network/)
- [Docker volumes](https://docs.docker.com/storage/volumes/)
