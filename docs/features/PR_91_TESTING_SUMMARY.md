# PR #91 Testing Summary: What's Needed Before Merge & Deploy

**PR:** [#91 - Optimize ML Model Loading](https://github.com/LocalNewsImpact/MizzouNewsCrawler/pull/91)  
**Date:** October 19, 2025

---

## Quick Answer

**What's Already Done:**
- ✅ Implementation complete
- ✅ Unit tests created and passing
- ✅ Documentation complete

**What's Needed Before Merging:**
1. **Run existing tests locally** (15 minutes)
2. **Local end-to-end test** (30 minutes)  
3. **Staging environment validation** (2-4 hours)

**Total Testing Time Required:** ~3-5 hours

---

## Priority Testing (Must Do Before Merge)

### 1. Run Unit Tests Locally ✅ (15 minutes)

```bash
cd /Users/kiesowd/VSCode/NewsCrawler/MizzouNewsCrawler-Scripts

# Run new caching tests
python -m pytest tests/test_continuous_processor_entity_caching.py -v

# Run updated processor tests
python -m pytest tests/test_continuous_processor.py::TestProcessEntityExtraction -v

# Run entity extraction command tests
python -m pytest tests/test_entity_extraction_command.py -v
```

**Expected:** All tests pass (green)

---

### 2. Local End-to-End Test 🔴 (30 minutes)

**Test the processor with cached model locally:**

```bash
# Activate your environment
source venv/bin/activate

# Run processor
python orchestration/continuous_processor.py

# Watch logs - look for:
# [INFO] 🧠 Loading spaCy model (one-time initialization)...  ← ONCE at startup
# [INFO] ✅ spaCy model loaded and cached in memory
# [INFO] ▶️  Entity extraction (N pending, limit 500)  ← Batch size is 500
# [INFO] ✅ Entity extraction completed successfully (Xs)

# Let it run through 2-3 entity extraction cycles (10-15 minutes)
# Ctrl+C to stop
```

**Success Criteria:**
- [ ] Model loads ONCE at startup
- [ ] Entity extraction runs successfully
- [ ] Batch size is 500 (not 50)
- [ ] No "Loading spaCy model" messages during batches
- [ ] No errors or crashes
- [ ] Memory stable (monitor with Activity Monitor ~2.5GB)

---

### 3. Staging Environment Test 🔴 (2-4 hours)

**Deploy to staging and validate:**

```bash
# 1. Build processor image
gcloud builds triggers run build-processor-manual \
  --branch=copilot/vscode1760881515439

# Wait for build (~3-5 minutes)

# 2. Deploy to staging (or update deployment manifest)
kubectl set image deployment/mizzou-processor \
  processor=gcr.io/PROJECT_ID/mizzou-processor:COMMIT_SHA \
  -n staging

# 3. Watch deployment
kubectl rollout status deployment/mizzou-processor -n staging

# 4. Monitor logs (15-30 minutes)
kubectl logs -f deployment/mizzou-processor -n staging | \
  grep -E "Loading spaCy|Entity extraction|✅|❌"

# 5. Monitor memory
kubectl top pod -n staging -l app=mizzou-processor

# 6. Let run for 2 hours minimum
```

**Success Criteria:**
- [ ] Pod starts successfully
- [ ] Model loads once (check logs)
- [ ] Entity extraction cycles complete
- [ ] Memory constant ~2.5GB
- [ ] No OOM kills for 2+ hours
- [ ] No errors in logs

---

## Additional Testing (Recommended)

### 4. Memory Profiling 🟡 (30 minutes)

```bash
# Install psutil if needed
pip install psutil

# Run memory benchmark
python -c "
import os, psutil, time
from orchestration import continuous_processor

process = psutil.Process(os.getpid())
baseline = process.memory_info().rss / 1024 / 1024
print(f'Baseline: {baseline:.1f} MB')

extractor = continuous_processor.get_cached_entity_extractor()
after_load = process.memory_info().rss / 1024 / 1024
print(f'After load: {after_load:.1f} MB (+{after_load - baseline:.1f} MB)')

for i in range(3):
    continuous_processor.process_entity_extraction(10)
    mem = process.memory_info().rss / 1024 / 1024
    print(f'After batch {i+1}: {mem:.1f} MB')
    time.sleep(5)

print('✅ Memory test complete')
"
```

**Expected:**
- Baseline: ~500MB
- After load: ~2500MB
- After batches: ~2500MB ± 200MB (stable)

---

### 5. Performance Benchmark 🟡 (15 minutes)

```bash
# Time entity extraction with cached model
time python -c "
from orchestration import continuous_processor
extractor = continuous_processor.get_cached_entity_extractor()
result = continuous_processor.process_entity_extraction(10)
print(f'Result: {result}')
"

# Expected: Should complete without loading model
# (model already cached)
```

---

### 6. Failure Mode Testing 🟡 (15 minutes)

```bash
# Test error handling
python -m pytest tests/test_continuous_processor.py -v -k error

# Test backward compatibility (CLI still works)
python -m src.cli.main extract-entities --limit 5

# Should work independently (creates own extractor)
```

---

## Pre-Deployment Checklist

**Before merging and deploying to production:**

- [ ] ✅ Unit tests pass locally
- [ ] 🔴 Local end-to-end test successful
- [ ] 🔴 Staging validated (2+ hours stable)
- [ ] 🟡 Memory profiling shows stable usage
- [ ] 🟡 Performance benchmarks acceptable
- [ ] ✅ Documentation complete
- [ ] ✅ Rollback plan ready
- [ ] 🔴 Team notified of deployment plan

**Legend:**
- ✅ = Already done
- 🔴 = Critical, must do
- 🟡 = Recommended

---

## Deployment Timeline Recommendation

### Option A: Conservative (Recommended)
```
Day 1: Local testing + Unit tests (2 hours)
Day 2: Deploy to staging + Monitor (4 hours)
Day 3: Continue staging monitoring (review after 24h)
Day 4: Deploy to production (maintenance window)
Day 5-6: Monitor production (24-48h)
```

**Total time:** 5-6 days

### Option B: Fast Track (If urgent)
```
Today:    Run all tests locally (3 hours)
Today:    Deploy to staging (evening)
Tomorrow: Validate staging (morning)
Tomorrow: Deploy to production (afternoon)
Weekend:  Monitor production
```

**Total time:** 2 days

---

## Production Deployment Steps

When ready to deploy:

```bash
# 1. Merge PR
git checkout feature/gcp-kubernetes-deployment
git merge copilot/vscode1760881515439
git push

# 2. Build production image
gcloud builds triggers run build-processor-manual \
  --branch=feature/gcp-kubernetes-deployment

# 3. Deploy to production
kubectl set image deployment/mizzou-processor \
  processor=gcr.io/PROJECT_ID/mizzou-processor:COMMIT_SHA \
  -n production

# 4. Monitor rollout
kubectl rollout status deployment/mizzou-processor -n production

# 5. Watch logs for 30 minutes
kubectl logs -f deployment/mizzou-processor -n production

# 6. Monitor memory
watch kubectl top pod -n production -l app=mizzou-processor

# 7. Continue monitoring for 24 hours
```

---

## Success Metrics (Post-Deployment)

After 24 hours in production, verify:

```bash
# Model should load exactly once per pod
kubectl logs deployment/mizzou-processor -n production | \
  grep -c "Loading spaCy model"
# Expected: 1 (or number of pods if multiple)

# Memory should be constant
kubectl top pod -n production -l app=mizzou-processor
# Expected: ~2.5Gi constant

# Entity extraction success rate
kubectl logs deployment/mizzou-processor -n production | \
  grep "Entity extraction" | \
  grep -c "completed successfully"
# Expected: High success rate

# No OOM events
kubectl get events -n production | grep -i oom
# Expected: No results
```

---

## Rollback Plan

If issues occur after deployment:

```bash
# Quick rollback
kubectl rollout undo deployment/mizzou-processor -n production

# Monitor rollback
kubectl rollout status deployment/mizzou-processor -n production

# Verify old behavior
kubectl logs -f deployment/mizzou-processor -n production
```

---

## Bottom Line

**Minimum Testing Required:**
1. ✅ Unit tests pass (15 min) - **DO THIS FIRST**
2. 🔴 Local end-to-end works (30 min) - **DO THIS TODAY**
3. 🔴 Staging stable for 2+ hours - **DO THIS BEFORE MERGE**

**Total Time:** ~3 hours minimum testing

**Recommendation:** Do conservative timeline (5-6 days) to ensure stability

---

## Next Steps

1. **Right now:** Run unit tests
2. **Today:** Local end-to-end testing
3. **Tomorrow:** Deploy to staging
4. **After 24h staging:** Merge PR
5. **Maintenance window:** Deploy to production

---

## Questions to Answer Before Merge

- [ ] Do all unit tests pass?
- [ ] Does the processor work locally with cached model?
- [ ] Is staging environment available?
- [ ] Is there a maintenance window scheduled?
- [ ] Is the team ready to monitor post-deployment?
- [ ] Is rollback plan tested?

---

**See full details:** `PR_91_TESTING_CHECKLIST.md`

**Contact:** @dkiesow for deployment approval
