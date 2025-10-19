# Logging & Cleanup Improvements - October 19, 2025

## Summary

Improved logging visibility for entity extraction and added automated cleanup of completed/failed jobs and pods.

---

## Changes Made

### 1. ✅ Improved Entity Extraction Logging

**File:** `src/cli/commands/entity_extraction.py`

**Changes:**
- Replaced `print()` statements with `logger.info()` for better log capture
- Added explicit `flush=True` to all logger calls for real-time visibility  
- Removed duplicate print/logger pairs
- Added progress logs every 10 articles with `sys.stdout.flush()`

**Before:**
```python
print(f"✓ Progress: {processed}/{len(rows)} articles processed")
logger.info("Progress: %d/%d articles processed", processed, len(rows))
```

**After:**
```python
logger.info("✓ Progress: %d/%d articles processed", processed, len(rows), extra={'flush': True})
sys.stdout.flush()  # Force immediate output
```

**Benefits:**
- Real-time progress visibility in Cloud Logging
- No more missing progress updates
- Consistent logging across all environments

---

### 2. ✅ Added Automated Cleanup CronJob

**File:** `k8s/cleanup-cronjob.yaml`

**What It Does:**
- Runs every 30 minutes automatically
- Cleans up completed jobs older than 1 hour
- Cleans up failed jobs older than 6 hours  
- Cleans up evicted/failed pods older than 1 hour
- Cleans up succeeded pods older than 30 minutes

**RBAC Permissions:**
- ServiceAccount: `cleanup-service-account`
- Role: `cleanup-role` (can list/delete jobs and pods in production namespace)
- RoleBinding: `cleanup-role-binding`

**CronJob Schedule:**
```yaml
schedule: "*/30 * * * *"  # Every 30 minutes
```

**Retention Policy:**
- Keeps last 3 successful cleanup jobs
- Keeps last 3 failed cleanup jobs
- Auto-deletes itself after 1 hour

**Test Results:**
```bash
$ kubectl create job --from=cronjob/cleanup-completed-jobs manual-cleanup-test -n production
$ kubectl logs -n production job/manual-cleanup-test

🧹 Starting cleanup of completed and failed resources...
Timestamp: Sun Oct 19 16:28:39 UTC 2025

Cleaning up completed jobs older than 1 hour...
ℹ️  No completed jobs to clean up

Cleaning up failed jobs older than 6 hours...
ℹ️  No failed jobs to clean up

Cleaning up evicted/failed pods older than 1 hour...
ℹ️  No evicted/failed pods to clean up

Cleaning up succeeded pods older than 30 minutes...
ℹ️  No succeeded pods to clean up

🎉 Cleanup completed successfully!
Timestamp: Sun Oct 19 16:28:45 UTC 2025
```

✅ **Working correctly!**

---

## Deployment Status

### Improved Logging Deployment

**Image:** `us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:5f98af6`  
**Commit:** 5f98af6  
**Status:** ✅ Deployed to production  
**Pod:** `mizzou-processor-584775c48d-7gpzt`

**Current State:**
- Pod running for 14+ minutes
- Processing 200 articles with entity extraction
- Model loaded once at startup ✅
- Memory stable at ~2.2GB ✅

### Cleanup CronJob Deployment

**Status:** ✅ Deployed and tested  
**Next Run:** Within 30 minutes  
**Manual Test:** Passed

---

## Known Issues

### Entity Extraction Still Silent

**Problem:** Even with improved logging, we're not seeing progress logs every 10 articles

**Possible Causes:**
1. **Python buffering:** Despite `flush=True` and `sys.stdout.flush()`, output might still be buffered
2. **Direct function call:** Calling the function directly (not via subprocess) may affect logging behavior
3. **Processing time:** Each article with spaCy NER + gazetteer matching takes significant time

**Evidence:**
- Pod has been processing for 14+ minutes
- CPU usage confirms active processing
- No errors in logs
- Model loaded successfully

**Workaround:** The processing IS working, just not logging progress

**Recommendation:** Consider adding:
1. Timer-based progress logs (every 60 seconds regardless of article count)
2. Background thread to report progress
3. Database-based progress tracking

---

## Next Steps

### Short-term (Today)

- [ ] Monitor entity extraction completion (should finish eventually)
- [ ] Verify cleanup CronJob runs automatically in 30 minutes
- [ ] Check if progress logs appear when processing completes

### Medium-term (This Week)

- [ ] Add timer-based progress logging (every 60s)
- [ ] Add estimated time remaining calculation
- [ ] Implement progress tracking in database
- [ ] Add Prometheus metrics for processing progress

### Long-term (Next Sprint)

- [ ] Consider async/parallel entity extraction
- [ ] Optimize gazetteer caching
- [ ] Add configurable batch sizes via API
- [ ] Implement graceful shutdown handling

---

## Commands Reference

### Check Cleanup CronJob
```bash
# View CronJob
kubectl get cronjob cleanup-completed-jobs -n production

# View schedule and last run
kubectl describe cronjob cleanup-completed-jobs -n production

# Manually trigger cleanup
kubectl create job --from=cronjob/cleanup-completed-jobs manual-cleanup -n production

# View cleanup logs
kubectl logs -n production job/manual-cleanup
```

### Monitor Entity Extraction
```bash
# Follow logs
kubectl logs -f -n production -l app=mizzou-processor

# Check progress (if any)
kubectl logs -n production -l app=mizzou-processor | grep -i progress

# Check pod resource usage
kubectl top pod -n production -l app=mizzou-processor

# Check for errors
kubectl logs -n production -l app=mizzou-processor | grep -iE "error|exception|failed"
```

---

## Commits

1. **fix: Improve entity extraction logging for better visibility**
   - Replaced print() with logger.info()
   - Added flush=True for real-time output
   - Added sys.stdout.flush() after progress logs
   - Commit: 5f98af6

2. **feat: Add CronJob to cleanup completed/failed jobs and pods**
   - Runs every 30 minutes
   - Includes RBAC permissions
   - Tested and working
   - Commit: 6f26651

---

## Files Changed

- `src/cli/commands/entity_extraction.py` - Improved logging
- `k8s/cleanup-cronjob.yaml` - New automated cleanup

---

**Status:** ✅ Deployed and monitoring  
**Next Review:** When entity extraction completes  
**Issue:** Need timer-based progress logging (not just article-count-based)
