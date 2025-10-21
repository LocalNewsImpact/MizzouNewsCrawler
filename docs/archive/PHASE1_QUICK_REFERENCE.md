# 🚀 Phase 1 Deployment - Quick Reference

**Date**: October 15, 2025  
**Phase**: 1 - Safe Feature-Flagged Deployment  
**Duration**: 2 days  
**Status**: Ready to Execute

---

## What's Being Deployed

### Code Changes
- **PR #78**: Orchestration refactor with feature flags
- **Files**: 11 modified (+1,425 lines, -52 lines)
- **Tests**: 32 passing ✅

### Behavior Changes
**BEFORE**: Processor handles all pipeline steps (discovery → extraction → cleaning → ML → entities)

**AFTER**: Processor handles only internal steps:
- ❌ Discovery (disabled)
- ❌ Verification (disabled)  
- ❌ Extraction (disabled)
- ✅ Cleaning (enabled)
- ✅ ML Analysis (enabled)
- ✅ Entity Extraction (enabled)

### Expected Impact
- **No new articles** will be extracted during Phase 1 (2 days)
- **Existing articles** continue processing (cleaning → ML → entities)
- **No data loss** - all tables unchanged
- **Safe rollback** - simple deployment revert

---

## Risks & Mitigation

### 🟡 Medium Risk: No New Articles for 2 Days
- **Impact**: Pipeline won't discover/extract new content
- **Mitigation**: Phase 1 is short (2 days), Phase 2 immediately restores extraction
- **Detection**: Monitor `candidate_links` count (should stay stable)

### 🔴 High Risk: Processor Fails to Start
- **Impact**: All processing stops (cleaning, ML, entities)
- **Mitigation**: 32 tests passing, liveness probes detect failures
- **Rollback**: `kubectl rollout undo deployment/mizzou-processor -n production`

### 🟢 Low Risk: Feature Flag Misconfiguration
- **Impact**: Wrong pipeline steps enabled/disabled
- **Detection**: Check logs for "Enabled pipeline steps" message
- **Fix**: Update deployment with correct flags

---

## Validation Tests (Before Phase 2)

All must pass to proceed:

### ✅ Test 1: Processor Health
```bash
kubectl get pods -n production -l app=mizzou-processor
# Expected: 1/1 Running, 0 restarts
```

### ✅ Test 2: Feature Flags Correct
```bash
kubectl logs -n production -l app=mizzou-processor --tail=200 | grep -A 10 "Enabled pipeline steps"
# Expected: Discovery ❌, Verification ❌, Extraction ❌, Cleaning ✅, ML ✅, Entities ✅
```

### ✅ Test 3: Processing Continues
```sql
-- Cleaning queue decreasing
SELECT COUNT(*) as cleaning_pending
FROM articles WHERE status = 'extracted';

-- ML analysis queue decreasing
SELECT COUNT(*) as analysis_pending
FROM articles WHERE status = 'cleaned' AND primary_label IS NULL;
```

### ✅ Test 4: No New Extractions
```sql
-- Should return 0 (extraction disabled)
SELECT COUNT(*) FROM articles
WHERE status = 'extracted' AND created_at > NOW() - INTERVAL '2 hours';
```

### ✅ Test 5: System Stability
```bash
# Error rate <10 errors/2 hours
kubectl logs -n production -l app=mizzou-processor --since=2h | grep -i "error" | wc -l

# Resource usage stable
kubectl top pod -n production -l app=mizzou-processor
```

---

## Deployment Steps

### Option 1: Automated Script (Recommended)

```bash
# Review the script first
cat scripts/deploy_phase1.sh

# Execute Phase 1 deployment
./scripts/deploy_phase1.sh
```

The script will:
1. ✅ Prompt for baseline metrics recording
2. ✅ Merge PR #78 to feature branch
3. ✅ Run tests (32 tests)
4. ✅ Push changes
5. ✅ Trigger Cloud Build
6. ✅ Verify new image
7. ✅ Prompt to update deployment YAML
8. ✅ Deploy to production
9. ✅ Validate feature flags

### Option 2: Manual Steps

See **PHASE1_DEPLOYMENT_TRACKER.md** for detailed manual steps.

---

## Monitoring (24 Hours)

### Real-Time Logs
```bash
kubectl logs -n production -l app=mizzou-processor --follow
```

### Check Work Queue Status
```bash
kubectl logs -n production -l app=mizzou-processor --tail=50 | grep "Work queue status"
```

### Database Queries
```sql
-- Pipeline status
SELECT 
  status,
  COUNT(*) as count
FROM articles
GROUP BY status;

-- Processing rate (last hour)
SELECT 
  DATE_TRUNC('hour', updated_at) as hour,
  status,
  COUNT(*) as count
FROM articles
WHERE updated_at > NOW() - INTERVAL '1 hour'
GROUP BY hour, status
ORDER BY hour DESC;
```

---

## Rollback Procedure

### If Deployment Fails
```bash
# Rollback to previous version
kubectl rollout undo deployment/mizzou-processor -n production

# Verify rollback
kubectl rollout status deployment/mizzou-processor -n production
kubectl logs -n production -l app=mizzou-processor --tail=50
```

### If Feature Flags Wrong
```bash
# Re-enable extraction (if needed)
kubectl set env deployment/mizzou-processor -n production \
  ENABLE_EXTRACTION=true \
  ENABLE_DISCOVERY=true \
  ENABLE_VERIFICATION=true

# Verify
kubectl get deployment mizzou-processor -n production -o yaml | grep -A 10 "ENABLE_"
```

---

## Go/No-Go Criteria

**All must pass to proceed to Phase 2:**

- [ ] ✅ Processor deployed without errors
- [ ] ✅ Pod running 24+ hours with 0 restarts
- [ ] ✅ Feature flags correct (external steps disabled)
- [ ] ✅ Processing continues (cleaning/ML/entity queues decreasing)
- [ ] ✅ No new extractions (expected)
- [ ] ✅ Error rate <10/2 hours
- [ ] ✅ No database connection issues
- [ ] ✅ Resource usage stable

**If all pass**: Proceed to Phase 2 (Mizzou Extraction Testing)

**If any fail**: Investigate, fix, and re-run Phase 1

---

## Quick Commands

### Check Processor Status
```bash
kubectl get pods -n production -l app=mizzou-processor
kubectl logs -n production -l app=mizzou-processor --tail=100
```

### View Current Image
```bash
kubectl get deployment mizzou-processor -n production -o jsonpath='{.spec.template.spec.containers[0].image}'
```

### Check Feature Flags
```bash
kubectl get deployment mizzou-processor -n production -o yaml | grep -A 6 "ENABLE_"
```

### Monitor Resource Usage
```bash
kubectl top pod -n production -l app=mizzou-processor
```

---

## Files Reference

- **Rollout Plan**: `PR78_ROLLOUT_PLAN.md` (full 4-week plan)
- **Phase 1 Tracker**: `PHASE1_DEPLOYMENT_TRACKER.md` (detailed tracking)
- **Deploy Script**: `scripts/deploy_phase1.sh` (automated deployment)
- **This File**: `PHASE1_QUICK_REFERENCE.md` (quick guide)

---

## Timeline

**Day 1** (Today, Oct 15):
- ✅ Establish baseline metrics
- ✅ Merge PR #78
- ✅ Build processor image
- ✅ Deploy to production
- ✅ Validate feature flags

**Day 2** (Oct 16):
- 🕐 Monitor for 24 hours
- 🕐 Run validation tests
- 🕐 Complete Phase 1 report
- 🕐 Make GO/NO-GO decision

**Day 3-7** (Oct 17-21):
- If GO: Phase 2 (Mizzou Extraction Testing)
- If NO-GO: Investigate issues, retry Phase 1

---

## Support

- **Documentation**: All `.md` files in this directory
- **PR #78**: https://github.com/LocalNewsImpact/MizzouNewsCrawler/pull/78
- **Issue #77**: https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/77

---

**Ready to Deploy?**

```bash
./scripts/deploy_phase1.sh
```

**Questions Before Deploying?**

Review `PHASE1_DEPLOYMENT_TRACKER.md` for complete details.

---

**Last Updated**: October 15, 2025  
**Next Review**: October 16, 2025 (after 24h monitoring)
