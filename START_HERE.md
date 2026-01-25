# 🎯 START HERE - Phase 1 Deployment

**Date**: October 15, 2025, 3:45 PM CST
**Action Required**: Deploy PR #78 Phase 1
**Time Required**: 15-20 minutes + 24h monitoring

---

## ✅ You Are Ready to Deploy

All preparation is complete:
- ✅ PR #78 created and reviewed (32 tests passing)
- ✅ Rollout plan documented (4-week strategy)
- ✅ Phase 1 tracker created (detailed steps)
- ✅ Deployment script ready (`scripts/deploy_phase1.sh`)
- ✅ Risks identified and mitigation planned
- ✅ Validation tests defined
- ✅ Rollback procedure documented

---

## 🚀 Execute Now (3 Simple Steps)

### Step 1: Record Baseline (5 minutes)

Open a SQL client and run these queries. **Copy the results** to a text file:

```sql
-- Baseline: Article counts
SELECT status, COUNT(*) as count
FROM articles
GROUP BY status
ORDER BY count DESC;

-- Baseline: Candidate link counts
SELECT status, COUNT(*) as count
FROM candidate_links
GROUP BY status
ORDER BY count DESC;

-- Baseline: Extraction rate (last 24 hours)
SELECT
  DATE_TRUNC('hour', created_at) as hour,
  COUNT(*) as articles
FROM articles
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY hour
ORDER BY hour DESC
LIMIT 24;
```

**Save results to**: `baseline_metrics_$(date +%Y%m%d).txt`

### Step 2: Run Deployment Script (10-15 minutes)

```bash
# Navigate to project directory
cd /Users/kiesowd/VSCode/NewsCrawler/MizzouNewsCrawler-Scripts

# Execute automated deployment
./scripts/deploy_phase1.sh
```

The script will:
1. ✅ Merge PR #78 to feature/gcp-kubernetes-deployment
2. ✅ Run 32 tests
3. ✅ Trigger Cloud Build
4. ✅ Deploy new processor image
5. ✅ Validate feature flags

**Follow the prompts** - the script will ask for confirmation at key steps.

### Step 3: Validate Deployment (5 minutes)

```bash
# Check processor is running
kubectl get pods -n production -l app=mizzou-processor

# Expected output:
# NAME                               READY   STATUS    RESTARTS   AGE
# mizzou-processor-xxxxxxxxxx-xxxxx  1/1     Running   0          2m

# Verify feature flags in logs
kubectl logs -n production -l app=mizzou-processor --tail=200 | grep -A 10 "Enabled pipeline steps"

# Expected output:
# Enabled pipeline steps:
#   - Discovery: ❌
#   - Verification: ❌
#   - Extraction: ❌
#   - Cleaning: ✅
#   - ML Analysis: ✅
#   - Entity Extraction: ✅
```

✅ **Deployment complete!**

---

## 📊 Monitor for 24 Hours

### Continuous Monitoring (keep this running)

```bash
# Stream processor logs
kubectl logs -n production -l app=mizzou-processor --follow
```

**What to look for**:
- ✅ No errors (occasional network issues are OK)
- ✅ "Work queue status" messages every minute
- ✅ `cleaning_pending`, `analysis_pending`, `entity_extraction_pending` decreasing
- ✅ `verification_pending` and `extraction_pending` = 0

### Periodic Checks (every 4-6 hours)

```bash
# Pod health
kubectl get pods -n production -l app=mizzou-processor

# Should show: 1/1 Running, 0 restarts

# Error count (should be <10 per 2 hours)
kubectl logs -n production -l app=mizzou-processor --since=2h | grep -i "error" | wc -l

# Resource usage (should be stable)
kubectl top pod -n production -l app=mizzou-processor
```

---

## ✅ Validation Tests (Tomorrow, Oct 16)

Run these tests **after 24 hours** of monitoring:

### Test 1: Processor Health ✅

```bash
kubectl get pods -n production -l app=mizzou-processor
```
**Pass criteria**: 1/1 Running, 0 restarts

### Test 2: Feature Flags ✅

```bash
kubectl logs -n production -l app=mizzou-processor --tail=200 | grep -A 10 "Enabled pipeline steps"
```
**Pass criteria**: Discovery ❌, Verification ❌, Extraction ❌, Cleaning ✅, ML ✅, Entities ✅

### Test 3: Processing Continues ✅

```sql
-- Run at 24h mark and compare to baseline
SELECT
  COUNT(CASE WHEN status = 'extracted' THEN 1 END) as cleaning_pending,
  COUNT(CASE WHEN status = 'cleaned' AND primary_label IS NULL THEN 1 END) as analysis_pending
FROM articles;
```
**Pass criteria**: Both numbers decreased since baseline

### Test 4: No New Extractions ✅

```sql
SELECT COUNT(*) as new_extractions
FROM articles
WHERE status = 'extracted' AND created_at > NOW() - INTERVAL '24 hours';
```
**Pass criteria**: Count = 0 (this is expected!)

### Test 5: System Stability ✅

```bash
# Error count
kubectl logs -n production -l app=mizzou-processor --since=24h | grep -i "error" | wc -l

# Resource usage
kubectl top pod -n production -l app=mizzou-processor
```
**Pass criteria**: Errors <50 in 24h, CPU/memory within 50% of baseline

---

## 🎯 Decision Point (Tomorrow Evening)

After running all 5 validation tests:

### If All Tests Pass → GO to Phase 2 ✅

**Action**: Proceed to Phase 2 (Mizzou Extraction Testing)

**Next steps**:
1. Review Phase 2 plan in `PR78_ROLLOUT_PLAN.md` (starting page ~15)
2. Deploy Mizzou extraction job (Week 1, Days 3-7)
3. Monitor parallel operation

### If Any Test Fails → NO-GO ⚠️

**Action**: Investigate and fix issue

**Possible actions**:
- Review logs for error patterns
- Check database connections
- Verify resource usage
- Consider rollback if critical

---

## 🔄 Emergency Rollback

**If deployment fails or processor crashes**:

```bash
# Immediate rollback
kubectl rollout undo deployment/mizzou-processor -n production

# Verify rollback
kubectl rollout status deployment/mizzou-processor -n production
kubectl get pods -n production -l app=mizzou-processor
kubectl logs -n production -l app=mizzou-processor --tail=50
```

**Time to recover**: <2 minutes
**Data loss**: None

---

## 📂 Documentation Quick Links

| Need | Document | Location |
|------|----------|----------|
| **Right now** | This file | `START_HERE.md` |
| **Quick reference** | Commands & tests | `PHASE1_QUICK_REFERENCE.md` |
| **Executive summary** | Risk & decisions | `PHASE1_EXECUTIVE_SUMMARY.md` |
| **Detailed tracking** | Full steps | `PHASE1_DEPLOYMENT_TRACKER.md` |
| **Complete plan** | All 6 phases | `PR78_ROLLOUT_PLAN.md` |
| **Deployment script** | Automation | `scripts/deploy_phase1.sh` |

---

## 🕐 Timeline

```
NOW (Oct 15, ~4:00 PM)
├── Record baseline (5 min)
├── Run deployment script (15 min)
└── Validate deployment (5 min)

TODAY Evening (Oct 15, 6:00 PM - 11:00 PM)
├── Monitor logs periodically
└── Check for any errors

TOMORROW Morning (Oct 16, 8:00 AM)
├── Check 12-hour stability
└── Review overnight logs

TOMORROW Afternoon (Oct 16, 3:00 PM)
├── Run all 5 validation tests
├── Complete Phase 1 report
└── Make GO/NO-GO decision

If GO:
THURSDAY (Oct 17)
└── Start Phase 2: Mizzou Extraction Testing
```

---

## 🎬 Action Items Checklist

### Right Now (Next 30 Minutes)
- [ ] Record baseline metrics (Step 1 above)
- [ ] Execute `./scripts/deploy_phase1.sh` (Step 2 above)
- [ ] Validate feature flags (Step 3 above)
- [ ] Set up continuous log monitoring

### Before End of Day
- [ ] Check processor health (6 PM, 9 PM)
- [ ] Review logs for any errors
- [ ] Confirm no unexpected behavior

### Tomorrow Morning
- [ ] Check 12-hour stability
- [ ] Review overnight logs
- [ ] Document any issues

### Tomorrow Afternoon
- [ ] Run all 5 validation tests
- [ ] Complete Phase 1 report in `PHASE1_DEPLOYMENT_TRACKER.md`
- [ ] Make GO/NO-GO decision with team
- [ ] Update todo list

---

## 💡 Key Reminders

### Expected Behavior (Normal)
- ✅ No new articles discovered/extracted during Phase 1
- ✅ Existing articles continue processing
- ✅ Processor logs show disabled steps
- ✅ `verification_pending` and `extraction_pending` = 0

### Unexpected Behavior (Investigate)
- ❌ Pod crashes or restarts
- ❌ High error rate (>50 errors/24h)
- ❌ Processing stops (queues not decreasing)
- ❌ Database connection errors
- ❌ Out of memory errors

### Questions During Deployment?
1. Check `PHASE1_QUICK_REFERENCE.md` for quick commands
2. Review `PHASE1_DEPLOYMENT_TRACKER.md` for detailed steps
3. See rollback procedure above if issues occur

---

## 🎯 Success Criteria

**Phase 1 is successful when**:
- ✅ Processor deployed and running for 24+ hours
- ✅ Feature flags correct (external steps disabled)
- ✅ Processing continues (cleaning/ML/entities working)
- ✅ No new extractions (expected behavior)
- ✅ System stable (low error rate, no crashes)

---

## 📞 Support

- **PR #78**: https://github.com/LocalNewsImpact/MizzouNewsCrawler/pull/78
- **Issue #77**: https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/77
- **Documentation**: All `.md` files in this directory

---

## 🚀 Ready? Let's Deploy!

```bash
# 1. Record baseline metrics (copy SQL results)
# 2. Execute deployment
./scripts/deploy_phase1.sh

# 3. Monitor for 24 hours
kubectl logs -n production -l app=mizzou-processor --follow
```

**Good luck!** 🎉

---

**Status**: ⏱️ READY TO EXECUTE
**Created**: October 15, 2025, 3:45 PM CST
**Next Review**: October 16, 2025, 3:00 PM CST (24h validation)
