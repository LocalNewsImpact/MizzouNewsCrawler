# Phase 1 Deployment Tracker - PR #78 Orchestration Refactor

**Phase**: 1 - Safe Feature-Flagged Deployment  
**Started**: October 15, 2025  
**Timeline**: Days 1-2 (2 days)  
**Status**: 🟡 IN PROGRESS  
**Risk Level**: ⚠️ Very Low

---

## Overview

Phase 1 deploys the refactored continuous processor with feature flags that disable external pipeline steps (discovery, verification, extraction). The processor will continue handling internal processing (cleaning, ML analysis, entity extraction) while external steps are migrated to dataset-specific jobs.

**Key Principle**: This is a **non-breaking deployment**. The processor behavior changes, but no data flow is interrupted.

---

## Changes Being Deployed

### 1. Code Changes (PR #78)

**Files Modified**: 11 files, +1,425 lines, -52 lines

#### Core Changes:
- **`orchestration/continuous_processor.py`**: Added feature flags to conditionally enable/disable pipeline steps
  ```python
  ENABLE_DISCOVERY = os.getenv("ENABLE_DISCOVERY", "false").lower() == "true"
  ENABLE_VERIFICATION = os.getenv("ENABLE_VERIFICATION", "false").lower() == "true"
  ENABLE_EXTRACTION = os.getenv("ENABLE_EXTRACTION", "false").lower() == "true"
  ENABLE_CLEANING = os.getenv("ENABLE_CLEANING", "true").lower() == "true"
  ENABLE_ML_ANALYSIS = os.getenv("ENABLE_ML_ANALYSIS", "true").lower() == "true"
  ENABLE_ENTITY_EXTRACTION = os.getenv("ENABLE_ENTITY_EXTRACTION", "true").lower() == "true"
  ```

- **`k8s/processor-deployment.yaml`**: Updated environment variables to disable external steps
  ```yaml
  - name: ENABLE_DISCOVERY
    value: "false"  # Moved to dataset jobs
  - name: ENABLE_VERIFICATION
    value: "false"  # Moved to dataset jobs
  - name: ENABLE_EXTRACTION
    value: "false"  # Moved to dataset jobs
  - name: ENABLE_CLEANING
    value: "true"   # Keep in continuous processor
  - name: ENABLE_ML_ANALYSIS
    value: "true"   # Keep in continuous processor
  - name: ENABLE_ENTITY_EXTRACTION
    value: "true"   # Keep in continuous processor
  ```

#### New Files:
- **`k8s/templates/dataset-discovery-job.yaml`**: Template for dataset-specific discovery jobs
- **`k8s/templates/dataset-extraction-job.yaml`**: Template for dataset-specific extraction jobs
- **`k8s/mizzou-discovery-job.yaml`**: Mizzou discovery job (used in Phase 3)
- **`k8s/mizzou-extraction-job.yaml`**: Mizzou extraction job (used in Phase 2)
- **`docs/ORCHESTRATION_ARCHITECTURE.md`**: Architecture documentation (395 lines)
- **`docs/ORCHESTRATION_MIGRATION.md`**: Migration guide (441 lines)

#### Test Coverage:
- **`tests/test_continuous_processor.py`**: 32 tests passing ✅
  - Feature flag validation tests
  - Conditional database query tests
  - Default configuration tests
  - Backward compatibility tests

### 2. Infrastructure Changes

**Current State** (before deployment):
- Processor: `processor:d0c043e` (from feature/gcp-kubernetes-deployment)
- Deployment: 1 replica, all pipeline steps enabled by default
- Resource limits: 750m CPU, 2Gi memory

**Target State** (after Phase 1):
- Processor: `processor:<new-sha>` (from copilot/refactor-pipeline-orchestration)
- Deployment: 1 replica, external steps disabled via feature flags
- Resource limits: 750m CPU, 2Gi memory (unchanged)
- Behavior: Only cleaning, ML analysis, entity extraction active

### 3. Database Impact

**No schema changes** - all tables remain the same.

**Expected behavior changes**:
- `candidate_links` table: No new `discovered` or `article` status updates (discovery/verification disabled)
- `articles` table: No new `extracted` status inserts (extraction disabled)
- Processing continues: `extracted → cleaned → labeled → entities`

---

## Risks Assessment

### ⚠️ Risk 1: New Articles Won't Be Discovered
**Severity**: Medium  
**Impact**: No new articles enter the pipeline during Phase 1  
**Mitigation**: 
- Phase 1 is intentionally short (2 days)
- Existing extracted articles will continue processing
- Phase 2 immediately adds Mizzou extraction back
**Detection**: Monitor `candidate_links` count - should remain stable
**Rollback**: Re-enable extraction in processor deployment

### ⚠️ Risk 2: Processor Fails to Start
**Severity**: High  
**Impact**: No article processing (cleaning, ML, entities)  
**Mitigation**: 
- All 32 tests passing in PR #78
- Feature flags have safe defaults
- Liveness/readiness probes will detect failures
**Detection**: Pod status shows CrashLoopBackOff
**Rollback**: `kubectl rollout undo deployment/mizzou-processor -n production`

### ⚠️ Risk 3: Feature Flag Misconfig
**Severity**: Low  
**Impact**: Processor may enable/disable wrong steps  
**Mitigation**: 
- Explicit values in deployment YAML
- Processor logs show enabled steps at startup
**Detection**: Check logs for "Enabled pipeline steps" message
**Rollback**: Update deployment with correct flags

### ⚠️ Risk 4: Database Connection Issues
**Severity**: Medium  
**Impact**: Processor can't read/write database  
**Mitigation**: 
- No changes to database connection code
- Cloud SQL Connector unchanged
**Detection**: Logs show connection errors
**Rollback**: Revert deployment

### ⚠️ Risk 5: Existing Extracted Articles Stuck
**Severity**: Low  
**Impact**: Articles in `extracted` status don't progress to `cleaned`  
**Mitigation**: 
- Cleaning step remains enabled
- No changes to cleaning logic
**Detection**: Query for stuck articles in `extracted` status
**Rollback**: Re-enable extraction to generate new articles

---

## Pre-Deployment Checklist

### ✅ Code Review
- [x] PR #78 reviewed and approved
- [x] All 32 tests passing
- [x] Documentation complete (836 lines)
- [ ] **TODO**: Final review of processor-deployment.yaml changes
- [ ] **TODO**: Verify feature flag defaults match expected behavior

### ✅ Infrastructure Ready
- [ ] **TODO**: Merge PR #78 to feature/gcp-kubernetes-deployment
- [ ] **TODO**: Trigger processor image build
- [ ] **TODO**: Verify new image in Artifact Registry
- [ ] **TODO**: Confirm current processor health (baseline)

### ✅ Monitoring Setup
- [ ] **TODO**: Establish baseline metrics (extraction rate, cleaning rate)
- [ ] **TODO**: Create kubectl alias for processor logs
- [ ] **TODO**: Prepare database queries for validation
- [ ] **TODO**: Set up alerts for pod restarts

### ✅ Communication
- [ ] **TODO**: Notify team of deployment window
- [ ] **TODO**: Document rollback procedure (accessible to team)
- [ ] **TODO**: Set up monitoring dashboard

---

## Deployment Steps (Day 1)

### Step 1: Establish Baseline Metrics

```bash
# Connect to Cloud SQL and record current state
# Run these queries before deployment

-- Count articles by status (baseline)
SELECT status, COUNT(*) as count
FROM articles
GROUP BY status
ORDER BY count DESC;

-- Count candidate links by status (baseline)
SELECT status, COUNT(*) as count
FROM candidate_links
GROUP BY status
ORDER BY count DESC;

-- Recent extraction rate (last 24 hours)
SELECT 
  DATE_TRUNC('hour', created_at) as hour,
  COUNT(*) as articles_created
FROM articles
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY hour
ORDER BY hour DESC;

-- Cleaning queue depth
SELECT COUNT(*) as cleaning_pending
FROM articles
WHERE status = 'extracted';

-- ML analysis queue depth
SELECT COUNT(*) as analysis_pending
FROM articles
WHERE status = 'cleaned' AND primary_label IS NULL;
```

**Expected baseline (approximate)**:
- Extracted articles: ~500-1000
- Cleaned articles: ~300-800
- Analyzed articles: ~200-600
- Extraction rate: ~5-20 articles/hour

### Step 2: Merge PR #78

```bash
# Switch to feature branch
cd /Users/kiesowd/VSCode/NewsCrawler/MizzouNewsCrawler-Scripts
git checkout feature/gcp-kubernetes-deployment
git pull origin feature/gcp-kubernetes-deployment

# Fetch PR branch
git fetch origin copilot/refactor-pipeline-orchestration

# Merge PR #78
git merge origin/copilot/refactor-pipeline-orchestration --no-ff -m "Merge PR #78: Refactor orchestration - Split dataset jobs from continuous processor"

# Review merge conflicts (if any)
git status

# Push merged changes
git push origin feature/gcp-kubernetes-deployment
```

**Validation**:
- [ ] No merge conflicts
- [ ] All tests still passing: `python -m pytest tests/test_continuous_processor.py -v`
- [ ] k8s/processor-deployment.yaml has correct feature flags

### Step 3: Trigger Processor Image Build

```bash
# Trigger Cloud Build for processor
gcloud builds triggers run build-processor-manual \
  --branch=feature/gcp-kubernetes-deployment

# Monitor build progress
gcloud builds list \
  --filter="trigger_id=build-processor-manual" \
  --limit=1 \
  --format="table(id,status,createTime,duration)"

# Get build ID for detailed logs
BUILD_ID=$(gcloud builds list --filter="trigger_id=build-processor-manual" --limit=1 --format="value(id)")

# Stream build logs
gcloud builds log $BUILD_ID --stream
```

**Expected duration**: 30-60 seconds (using ml-base image)

**Validation**:
- [ ] Build status: SUCCESS
- [ ] All 7 build steps completed
- [ ] Image pushed to Artifact Registry

### Step 4: Verify New Image

```bash
# List recent processor images
gcloud artifacts docker images list \
  us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor \
  --limit=5 \
  --sort-by=~CREATE_TIME \
  --format="table(package,version,createTime,updateTime)"

# Get the latest image SHA
NEW_IMAGE_SHA=$(gcloud artifacts docker images list \
  us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor \
  --limit=1 \
  --sort-by=~CREATE_TIME \
  --format="value(version)")

echo "New processor image: processor:$NEW_IMAGE_SHA"
```

**Record the new image SHA**: `processor:___________`

**Validation**:
- [ ] New image exists in Artifact Registry
- [ ] Image created today (October 15, 2025)
- [ ] Image size reasonable (~1-2GB)

---

## Deployment Steps (Day 2)

### Step 5: Update Processor Deployment

```bash
# Verify current processor status (before deployment)
kubectl get pods -n production -l app=mizzou-processor
kubectl logs -n production -l app=mizzou-processor --tail=50

# Record current image
CURRENT_IMAGE=$(kubectl get deployment mizzou-processor -n production -o jsonpath='{.spec.template.spec.containers[0].image}')
echo "Current image: $CURRENT_IMAGE"

# Update deployment with new image (if k8s/processor-deployment.yaml wasn't updated)
kubectl set image deployment/mizzou-processor \
  processor=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:$NEW_IMAGE_SHA \
  -n production

# OR apply the updated YAML (if it has the new image SHA)
kubectl apply -f k8s/processor-deployment.yaml

# Watch rollout
kubectl rollout status deployment/mizzou-processor -n production --timeout=5m
```

**Expected output**:
```
Waiting for deployment "mizzou-processor" rollout to finish: 1 old replicas are pending termination...
Waiting for deployment "mizzou-processor" rollout to finish: 1 old replicas are pending termination...
deployment "mizzou-processor" successfully rolled out
```

**Validation**:
- [ ] Rollout completes successfully
- [ ] New pod reaches Running state
- [ ] Old pod terminates cleanly

### Step 6: Verify Feature Flags

```bash
# Check processor logs for feature flag status
kubectl logs -n production -l app=mizzou-processor --tail=200 | grep -A 10 "Enabled pipeline steps"
```

**Expected output**:
```
🚀 Starting continuous processor
Configuration:
  - Poll interval: 60 seconds
  ...

Enabled pipeline steps:
  - Discovery: ❌
  - Verification: ❌
  - Extraction: ❌
  - Cleaning: ✅
  - ML Analysis: ✅
  - Entity Extraction: ✅
```

**Validation**:
- [ ] Discovery: ❌ (disabled)
- [ ] Verification: ❌ (disabled)
- [ ] Extraction: ❌ (disabled)
- [ ] Cleaning: ✅ (enabled)
- [ ] ML Analysis: ✅ (enabled)
- [ ] Entity Extraction: ✅ (enabled)

### Step 7: Monitor Work Queue

```bash
# Watch processor logs for work queue status
kubectl logs -n production -l app=mizzou-processor --follow
```

**Expected behavior**:
```
Work queue status: {
  'verification_pending': 0,      # Should be 0 (verification disabled)
  'extraction_pending': 0,        # Should be 0 (extraction disabled)
  'cleaning_pending': 25,         # Should decrease as articles are cleaned
  'analysis_pending': 30,         # Should decrease as articles are analyzed
  'entity_extraction_pending': 40 # Should decrease as entities are extracted
}

✅ Content cleaning (25 pending, limit 128) completed successfully
✅ ML classification (30 pending, limit 128) completed successfully
✅ Entity extraction (40 pending, limit 50) completed successfully
```

**Validation**:
- [ ] `verification_pending` = 0 (no new verifications)
- [ ] `extraction_pending` = 0 (no new extractions)
- [ ] `cleaning_pending` decreases over time
- [ ] `analysis_pending` decreases over time
- [ ] `entity_extraction_pending` decreases over time
- [ ] No errors in logs

---

## Validation Tests (Day 2, Afternoon)

### Test 1: Processor Health

```bash
# Check pod status
kubectl get pods -n production -l app=mizzou-processor

# Expected: 1/1 Running
# Check restart count - should be 0

# Check pod events
kubectl describe pod -n production -l app=mizzou-processor | grep -A 10 Events
```

**Pass criteria**:
- [ ] Pod status: Running
- [ ] Restart count: 0
- [ ] No error events
- [ ] Liveness probe: Success
- [ ] Readiness probe: Success

### Test 2: Database Queue Progression

```sql
-- Run these queries before and after 2 hours

-- Cleaning queue (should decrease)
SELECT COUNT(*) as cleaning_pending
FROM articles
WHERE status = 'extracted';

-- ML analysis queue (should decrease)
SELECT COUNT(*) as analysis_pending
FROM articles
WHERE status = 'cleaned' AND primary_label IS NULL;

-- Entity extraction queue (should decrease)
SELECT COUNT(*) as entity_extraction_pending
FROM articles a
WHERE a.primary_label IS NOT NULL
AND NOT EXISTS (
  SELECT 1 FROM article_entities ae WHERE ae.article_id = a.id
);

-- New extractions (should remain at 0)
SELECT COUNT(*) as new_extractions
FROM articles
WHERE status = 'extracted'
AND created_at > NOW() - INTERVAL '2 hours';
```

**Pass criteria**:
- [ ] `cleaning_pending` decreased (articles moving to `cleaned`)
- [ ] `analysis_pending` decreased (articles getting labeled)
- [ ] `entity_extraction_pending` decreased (entities extracted)
- [ ] `new_extractions` = 0 (no new extractions, as expected)

### Test 3: No New Discovery/Extraction

```sql
-- Should return 0 (no new discovered links)
SELECT COUNT(*) as new_discovered
FROM candidate_links
WHERE status = 'discovered'
AND created_at > NOW() - INTERVAL '2 hours';

-- Should return 0 (no new article verifications)
SELECT COUNT(*) as new_verified
FROM candidate_links
WHERE status = 'article'
AND updated_at > NOW() - INTERVAL '2 hours';

-- Should return 0 (no new extractions)
SELECT COUNT(*) as new_extracted
FROM articles
WHERE status = 'extracted'
AND created_at > NOW() - INTERVAL '2 hours';
```

**Pass criteria**:
- [ ] `new_discovered` = 0 (discovery disabled)
- [ ] `new_verified` = 0 (verification disabled)
- [ ] `new_extracted` = 0 (extraction disabled)

### Test 4: Existing Articles Continue Processing

```sql
-- Articles moving through pipeline (last 2 hours)
SELECT 
  status,
  COUNT(*) as count
FROM articles
WHERE updated_at > NOW() - INTERVAL '2 hours'
GROUP BY status
ORDER BY 
  CASE status
    WHEN 'extracted' THEN 1
    WHEN 'cleaned' THEN 2
    WHEN 'analyzed' THEN 3
    ELSE 4
  END;
```

**Expected results**:
- Articles transitioning from `extracted → cleaned`
- Articles transitioning from `cleaned → analyzed`
- No new `extracted` articles

**Pass criteria**:
- [ ] Articles continue progressing through pipeline
- [ ] No articles stuck in `extracted` status for >2 hours
- [ ] Cleaning, ML, entity extraction all functioning

### Test 5: Resource Usage

```bash
# Check processor CPU and memory usage
kubectl top pod -n production -l app=mizzou-processor

# Expected: Similar to baseline
# CPU: ~100-300m
# Memory: ~500Mi-1Gi
```

**Pass criteria**:
- [ ] CPU usage stable (within 50% of baseline)
- [ ] Memory usage stable (within 50% of baseline)
- [ ] No OOMKilled events

### Test 6: Error Rate

```bash
# Check for errors in logs (last 2 hours)
kubectl logs -n production -l app=mizzou-processor --since=2h | grep -i "error\|exception\|failed" | wc -l

# Expected: <10 errors (mostly transient network issues)
```

**Pass criteria**:
- [ ] Error count <10 in 2 hours
- [ ] No database connection errors
- [ ] No Cloud SQL Connector errors
- [ ] No critical exceptions

---

## Rollback Procedure

**Trigger rollback if**:
- Pod enters CrashLoopBackOff
- Error rate >50 errors/hour
- Database connection failures
- Processing stops (queues not decreasing)

### Rollback Steps

```bash
# Option 1: Rollback to previous deployment
kubectl rollout undo deployment/mizzou-processor -n production

# Verify rollback
kubectl rollout status deployment/mizzou-processor -n production
kubectl get pods -n production -l app=mizzou-processor

# Check logs
kubectl logs -n production -l app=mizzou-processor --tail=50

# Option 2: Re-enable extraction manually (if deployment works but behavior wrong)
kubectl set env deployment/mizzou-processor -n production \
  ENABLE_DISCOVERY=true \
  ENABLE_VERIFICATION=true \
  ENABLE_EXTRACTION=true

# Verify environment variables
kubectl get deployment mizzou-processor -n production -o yaml | grep -A 10 "ENABLE_"
```

**Post-Rollback Validation**:
- [ ] Pod running and healthy
- [ ] Processor logs show all steps enabled
- [ ] New extractions appearing in database
- [ ] Error rate returns to baseline

---

## Go/No-Go Criteria for Phase 2

**All must pass to proceed to Phase 2**:

### ✅ Deployment Success
- [ ] Processor deployed without errors
- [ ] Pod running for 24+ hours with 0 restarts
- [ ] Feature flags correctly configured

### ✅ Processing Continues
- [ ] Cleaning queue decreasing
- [ ] ML analysis queue decreasing
- [ ] Entity extraction queue decreasing
- [ ] No articles stuck in `extracted` status >4 hours

### ✅ No New External Activity
- [ ] No new discoveries (`candidate_links` with `status='discovered'`)
- [ ] No new verifications (`candidate_links` updated to `status='article'`)
- [ ] No new extractions (`articles` with `status='extracted'`)

### ✅ System Stability
- [ ] Error rate <10 errors/2 hours
- [ ] No database connection issues
- [ ] Resource usage stable (CPU, memory within 50% of baseline)
- [ ] No pod restarts or crashes

### ✅ Monitoring Operational
- [ ] Processor logs accessible via kubectl
- [ ] Database queries working
- [ ] Alerts configured (if applicable)

---

## Phase 1 Completion Report

**To be filled out on Day 2 evening**:

### Deployment Summary
- Merge completed: [YES/NO] at [TIMESTAMP]
- Build completed: [YES/NO] - Build ID: [BUILD_ID]
- Image deployed: [YES/NO] - processor:[IMAGE_SHA]
- Rollout completed: [YES/NO] at [TIMESTAMP]

### Validation Results
- Processor health: [PASS/FAIL]
- Feature flags correct: [PASS/FAIL]
- Processing continues: [PASS/FAIL]
- No new extractions: [PASS/FAIL]
- System stability: [PASS/FAIL]

### Metrics Comparison

| Metric | Baseline (Before) | After 24h | Change |
|--------|-------------------|-----------|---------|
| Cleaning pending | ___ | ___ | ___% |
| Analysis pending | ___ | ___ | ___% |
| Entity extraction pending | ___ | ___ | ___% |
| New extractions (24h) | ___ | 0 | -100% |
| Error count (24h) | ___ | ___ | ___% |
| Pod restarts | 0 | ___ | ___ |

### Issues Encountered
- [List any issues, workarounds, or unexpected behavior]

### Decision for Phase 2
- [ ] ✅ **GO** - All criteria met, proceed to Phase 2 (Mizzou Extraction Testing)
- [ ] ⚠️ **NO-GO** - Issues detected, investigate and retry Phase 1
- [ ] 🔄 **ROLLBACK** - Critical issues, revert to previous state

---

## Next Steps (if GO)

Once Phase 1 validation passes, proceed to Phase 2:

1. Review **Phase 2 deployment plan** (Week 1, Days 3-7)
2. Deploy Mizzou extraction job
3. Monitor for 48+ hours
4. Validate parallel operation with continuous processor

**Phase 2 Kickoff Meeting**: Schedule after Phase 1 completion

---

**Document Status**: 🟡 IN PROGRESS  
**Last Updated**: October 15, 2025  
**Next Review**: October 16, 2025 (Day 2 validation)
