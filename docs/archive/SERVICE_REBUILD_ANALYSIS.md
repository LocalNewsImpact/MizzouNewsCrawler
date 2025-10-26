# Service Rebuild Analysis - After Recent Changes

## Changed Files in Commit 3fe42ce

### Source Code Changes:
1. **src/crawler/discovery.py** - RSS feed discovery logic
2. **src/crawler/scheduling.py** - Scheduling cadence logic
3. **src/models/telemetry_orm.py** - ORM models for telemetry
4. **src/pipeline/entity_extraction.py** - Entity extraction with gazetteer
5. **src/utils/comprehensive_telemetry.py** - Telemetry utilities

### Migration Changes:
6. **alembic/versions/805164cd4665_*.py** - Database migration

### CI/Documentation Changes:
7. **.github/workflows/ci.yml** - CI configuration (no rebuild needed)
8. **CI_LOCAL_STANDARDS_COMPARISON.md** - Documentation (no rebuild needed)
9. **coverage.xml** - Test coverage report (no rebuild needed)

### Test Changes:
10. **tests/** - Multiple test files (no rebuild needed)

---

## 🚀 Services That MUST Be Rebuilt

### 1. ✅ **CRAWLER** - HIGH PRIORITY
**Why**: Uses changed source files directly
- ✅ `src/crawler/discovery.py` - RSS metadata fix (CRITICAL)
- ✅ `src/crawler/scheduling.py` - Float conversion fix
- ✅ `src/models/telemetry_orm.py` - New ORM models
- ✅ `src/utils/comprehensive_telemetry.py` - Telemetry updates

**Impact**: Production-critical RSS metadata bug fix
**Rebuild**: REQUIRED
```bash
gcloud builds triggers run build-crawler-manual \
  --branch=feature/gcp-kubernetes-deployment
```

### 2. ✅ **PROCESSOR** - HIGH PRIORITY  
**Why**: Uses changed source files directly
- ✅ `src/pipeline/entity_extraction.py` - Gazetteer OR logic fix
- ✅ `src/models/telemetry_orm.py` - New ORM models
- ✅ `src/utils/comprehensive_telemetry.py` - Telemetry updates

**Impact**: Entity extraction filtering fix
**Rebuild**: REQUIRED
```bash
gcloud builds triggers run build-processor-manual \
  --branch=feature/gcp-kubernetes-deployment
```

### 3. ⚠️ **API** - MEDIUM PRIORITY
**Why**: May use ORM models and telemetry utilities
- ⚠️ `src/models/telemetry_orm.py` - New ORM models (if API queries telemetry)
- ⚠️ `src/utils/comprehensive_telemetry.py` - If API writes telemetry

**Impact**: ORM schema changes for telemetry queries
**Rebuild**: RECOMMENDED (for consistency)
```bash
gcloud builds triggers run build-api-manual \
  --branch=feature/gcp-kubernetes-deployment
```

### 4. ✅ **MIGRATOR** - REQUIRED
**Why**: Database migration changed
- ✅ `alembic/versions/805164cd4665_*.py` - UNIQUE constraint for http_error_summary

**Impact**: Must run migration before deploying services
**Rebuild**: REQUIRED (run FIRST)
```bash
# Check if migrator image needs rebuild
gcloud artifacts docker tags list \
  us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/migrator

# If needed, rebuild:
gcloud builds submit --config cloudbuild-migrator.yaml

# Then run migration:
kubectl apply -f k8s/migration-job.yaml
kubectl logs -f job/migration-job
```

---

## 📋 Deployment Order

### CRITICAL: Deploy in this order to avoid errors

```bash
# Step 1: Run Database Migration FIRST
# (Ensures http_error_summary UNIQUE constraint exists)
kubectl delete job migration-job --ignore-not-found
kubectl apply -f k8s/migration-job.yaml
kubectl wait --for=condition=complete --timeout=300s job/migration-job
kubectl logs job/migration-job

# Step 2: Rebuild & Deploy Crawler (RSS metadata fix)
gcloud builds triggers run build-crawler-manual \
  --branch=feature/gcp-kubernetes-deployment

# Wait for build to complete, then deploy
# (Or use Cloud Deploy if configured)

# Step 3: Rebuild & Deploy Processor (entity extraction fix)
gcloud builds triggers run build-processor-manual \
  --branch=feature/gcp-kubernetes-deployment

# Step 4: Rebuild & Deploy API (ORM consistency)
gcloud builds triggers run build-api-manual \
  --branch=feature/gcp-kubernetes-deployment
```

---

## 🔍 Service-to-Source Mapping

### Crawler Service
**Dockerfile**: `Dockerfile.crawler`
**Source Files Used**:
- ✅ `src/crawler/` - ALL FILES (discovery.py, scheduling.py changed)
- ✅ `src/models/` - ORM models
- ✅ `src/utils/` - Utilities including telemetry
- `src/pipeline/` - Some extraction utilities
- `backend/` - NOT USED

**Changed Files Impact**: HIGH (2 direct files changed)

### Processor Service  
**Dockerfile**: `Dockerfile.processor`
**Source Files Used**:
- ✅ `src/pipeline/` - ALL FILES (entity_extraction.py changed)
- ✅ `src/models/` - ORM models
- ✅ `src/utils/` - Utilities including telemetry
- `src/crawler/` - NOT USED
- `backend/` - NOT USED

**Changed Files Impact**: HIGH (1 direct file changed)

### API Service
**Dockerfile**: `Dockerfile.api`  
**Source Files Used**:
- `backend/` - FastAPI application
- ⚠️ `src/models/` - ORM models (if querying telemetry)
- ⚠️ `src/utils/` - Some utilities
- `src/crawler/` - NOT USED
- `src/pipeline/` - NOT USED

**Changed Files Impact**: MEDIUM (ORM changes may affect queries)

---

## ⚡ Quick Deploy Commands

### Option A: Deploy All Services (Recommended)
```bash
# Build all in parallel
gcloud builds triggers run build-crawler-manual --branch=feature/gcp-kubernetes-deployment &
gcloud builds triggers run build-processor-manual --branch=feature/gcp-kubernetes-deployment &
gcloud builds triggers run build-api-manual --branch=feature/gcp-kubernetes-deployment &
wait

# Then deploy via kubectl or Cloud Deploy
```

### Option B: Use Task Runner (if available)
```bash
# Check available tasks
make -C tasks/ list

# Deploy all services
make -C tasks/ deploy-all-services
```

### Option C: Individual Service Deployment
```bash
# Crawler only (RSS fix priority)
gcloud builds triggers run build-crawler-manual \
  --branch=feature/gcp-kubernetes-deployment

# Processor only (entity extraction fix)
gcloud builds triggers run build-processor-manual \
  --branch=feature/gcp-kubernetes-deployment

# API only (ORM consistency)
gcloud builds triggers run build-api-manual \
  --branch=feature/gcp-kubernetes-deployment
```

---

## 🎯 Priority Summary

| Service | Priority | Reason | Critical Fix |
|---------|----------|--------|--------------|
| **Migrator** | 🔴 CRITICAL | Database schema change | UNIQUE constraint |
| **Crawler** | 🔴 CRITICAL | RSS metadata bug | Production bug fix |
| **Processor** | 🟡 HIGH | Entity extraction fix | Gazetteer OR logic |
| **API** | 🟢 MEDIUM | ORM consistency | Schema alignment |

---

## ✅ Verification After Deployment

### Check Crawler
```bash
kubectl logs -n production -l app=crawler --tail=50 | grep -i "rss\|metadata\|scheduling"
```

### Check Processor  
```bash
kubectl logs -n production -l app=processor --tail=50 | grep -i "entity\|gazetteer\|extraction"
```

### Check Telemetry
```bash
# Query Cloud SQL to verify ORM changes work
gcloud sql connect mizzou-crawler-instance --user=postgres
# Run: SELECT COUNT(*) FROM extraction_telemetry_v2;
# Run: SELECT COUNT(*) FROM http_error_summary;
```

---

## 📊 Build Time Estimates

- **Base Image**: Already built, reuse existing
- **ML Base**: Already built, reuse existing  
- **Crawler**: ~2-3 minutes (depends on base)
- **Processor**: ~1-2 minutes (uses ml-base)
- **API**: ~1-2 minutes (depends on base)
- **Total Sequential**: ~6-8 minutes
- **Total Parallel**: ~3-4 minutes

---

**RECOMMENDATION**: Rebuild and deploy CRAWLER and PROCESSOR immediately (production-critical fixes). Rebuild API for consistency. Run migration FIRST before any service deployment.
