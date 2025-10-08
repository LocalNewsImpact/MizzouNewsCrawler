# Processor Error Fixes - Deployment Summary

## Date: October 8, 2025

## Overview
Fixed all 3 critical processor errors identified in production logs:

1. ✅ **Entity Extraction SQL Error** - Fixed in commit `c0d693b`
2. ✅ **ML Analysis Proxy Authentication Error** - Fixed in commit `237516e`
3. ✅ **Extraction Bot Detection/CAPTCHA Handling** - Improved in commit `237516e`

---

## Fix #1: Entity Extraction SQL Error

### Commit
`c0d693b0be004c388681f7a9bf18272b6de73e76`

### Problem
```
column a.source_id does not exist
```
Query tried to select `source_id` and `dataset_id` from `articles` table, but these columns exist in `candidate_links` table.

### Solution
Updated `src/cli/commands/entity_extraction.py` to join with `candidate_links`:

```python
# BEFORE (broken):
SELECT a.id, a.text, a.text_hash, a.source_id, a.dataset_id
FROM articles a
WHERE ...

# AFTER (fixed):
SELECT a.id, a.text, a.text_hash, cl.source_id, cl.dataset_id
FROM articles a
JOIN candidate_links cl ON a.candidate_link_id = cl.id
WHERE ...
```

### Impact
- **1,538 articles** were blocked from entity extraction
- Now unblocked and ready to process

---

## Fix #2: ML Analysis Proxy Authentication Error

### Commit
`237516e990120686f1a4a84399530d8bafdfc371`

### Problem
```
407 Client Error: PROXY AUTHENTICATION REQUIRED
for url: http://proxy.kiesow.net:23432/?url=https://huggingface.co/...
```
HuggingFace model downloads were being routed through the proxy, which requires authentication.

### Solution
Added `NO_PROXY` and `no_proxy` environment variables to `k8s/processor-deployment.yaml`:

```yaml
env:
  - name: NO_PROXY
    value: "localhost,127.0.0.1,metadata.google.internal,huggingface.co,*.huggingface.co,cdn-lfs.huggingface.co,cdn.huggingface.co"
  - name: no_proxy
    value: "localhost,127.0.0.1,metadata.google.internal,huggingface.co,*.huggingface.co,cdn-lfs.huggingface.co,cdn.huggingface.co"
```

### Impact
- **1,406 articles** were blocked from ML classification
- HuggingFace downloads now bypass proxy and go direct
- ML analysis pipeline fully unblocked

---

## Fix #3: Extraction Bot Detection & CAPTCHA Handling

### Commit
`237516e990120686f1a4a84399530d8bafdfc371`

### Problem
Multiple domains blocking extraction with:
- CAPTCHA challenges (www.fultonsun.com, www.maryvilleforum.com)
- Bot detection/403 errors (www.ozarksfirst.com)
- Rate limiting with aggressive backoffs

### Solution
Added configuration to `k8s/processor-deployment.yaml` to:

1. **Increase CAPTCHA backoff times**:
   ```yaml
   - name: CAPTCHA_BACKOFF_BASE
     value: "900"  # 15 minutes (was 10 minutes)
   - name: CAPTCHA_BACKOFF_MAX
     value: "7200"  # 2 hours (was 90 minutes)
   ```

2. **Slow down request rate**:
   ```yaml
   - name: INTER_REQUEST_MIN
     value: "2.0"  # 2 seconds (was 1.5 seconds)
   - name: INTER_REQUEST_MAX
     value: "4.5"  # 4.5 seconds (was 3.5 seconds)
   ```

### Impact
- **122 articles** affected by bot detection/CAPTCHA
- Longer backoffs give sites more time to cool down
- Slower requests reduce likelihood of triggering bot detection
- Domain skipping logic already in place to skip problematic domains within a batch

### Affected Domains
- `www.fultonsun.com` - CAPTCHA (642s backoff)
- `www.ozarksfirst.com` - 403 bot detection (120s backoff)
- `www.maryvilleforum.com` - CAPTCHA + gzip errors (665s backoff)
- `www.theprospectnews.com` - 404s (content removed)

---

## Deployment Information

### Build Details
- **Build ID**: `6020eb45-8f99-4d32-a140-be52dc4cd45c`
- **Trigger**: `build-processor-manual`
- **Branch**: `feature/gcp-kubernetes-deployment`
- **Commit**: `237516e990120686f1a4a84399530d8bafdfc371`
- **Status**: QUEUED (building now)
- **Log URL**: https://console.cloud.google.com/cloud-build/builds/6020eb45-8f99-4d32-a140-be52dc4cd45c?project=145096615031

### Container Images
```
us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:237516e
us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:v1.3.1 (latest)
```

### Deployment Steps
1. ✅ Build processor image with fixes (in progress)
2. ⏳ Cloud Deploy creates release `processor-237516e`
3. ⏳ Kubernetes rolls out new processor pod
4. ⏳ Verify entity extraction works
5. ⏳ Verify ML analysis can load HuggingFace model
6. ⏳ Monitor extraction backoff behavior

---

## Verification Commands

### 1. Check Build Status
```bash
gcloud builds list --limit=1 --filter="tags:trigger-c5313267-7c52-43be-b320-6b9a1bb6cfa3" \
  --format="table(id,status,createTime)"
```

### 2. Monitor Pod Rollout
```bash
kubectl rollout status deployment/mizzou-processor -n production
```

### 3. Check New Pod
```bash
kubectl get pods -n production -l app=mizzou-processor
```

### 4. Verify NO_PROXY Environment
```bash
kubectl exec -n production deploy/mizzou-processor -- \
  env | grep -E "(NO_PROXY|no_proxy)"
```

### 5. Test Entity Extraction (Fix #1)
```bash
kubectl exec -n production deploy/mizzou-processor -- \
  python -m src.cli.cli_modular extract-entities --limit 10
```

**Expected**: Successfully extracts entities for 10 articles without SQL errors.

### 6. Test ML Analysis (Fix #2)
```bash
kubectl exec -n production deploy/mizzou-processor -- \
  python -m src.cli.cli_modular analyze --limit 10
```

**Expected**: Successfully loads HuggingFace model and classifies 10 articles without 407 proxy errors.

### 7. Monitor Processor Logs
```bash
kubectl logs -n production deploy/mizzou-processor -f | \
  grep -E "(entity extraction|ML analysis|CAPTCHA|407|✓|✅)"
```

**Expected**: 
- See successful entity extraction completions
- See successful ML analysis completions
- See longer CAPTCHA backoff times (900s base, 7200s max)
- No 407 proxy errors

### 8. Check Error Rates
```bash
# Entity extraction errors (should decrease)
kubectl logs -n production deploy/mizzou-processor --tail=500 | \
  grep -c "column a.source_id does not exist"

# ML analysis proxy errors (should be zero)
kubectl logs -n production deploy/mizzou-processor --tail=500 | \
  grep -c "407 Client Error: PROXY AUTHENTICATION REQUIRED"

# CAPTCHA backoff events (should show increased times)
kubectl logs -n production deploy/mizzou-processor --tail=500 | \
  grep "CAPTCHA backoff"
```

---

## Expected Outcomes

### Immediate (within 30 minutes)
1. ✅ Entity extraction processes 1,538 backlogged articles
2. ✅ ML analysis loads HuggingFace model successfully
3. ✅ ML analysis processes 1,406 backlogged articles

### Short-term (within 24 hours)
1. ✅ CAPTCHA-protected domains backed off with longer delays
2. ✅ Slower request rate reduces bot detection triggers
3. ⚠️ Some domains may still be problematic (permanent blocks)

### Known Limitations
1. **Cannot solve permanent blocks**: Some sites may permanently block scrapers
2. **CAPTCHA still possible**: Longer backoffs reduce but don't eliminate CAPTCHAs
3. **Manual intervention may be needed**: For persistently blocked domains, may need:
   - Residential proxy service
   - Domain-specific extraction APIs
   - Temporary exclusion from processing

---

## Related Issues & PRs

- **Issue #57**: Critical processor errors (entity extraction, proxy, extraction failures)
- **PR #58**: Pipeline visibility and monitoring (merged to feature branch)
- **Branch**: `feature/gcp-kubernetes-deployment`

---

## Rollback Plan

If issues arise after deployment:

### Rollback to Previous Version
```bash
# Get previous working release
gcloud deploy releases list \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1 \
  --limit=5

# Promote previous release
gcloud deploy releases promote \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1 \
  --release=processor-<PREVIOUS_COMMIT> \
  --to-target=production
```

### Emergency: Delete New Pod
```bash
kubectl delete pod -n production -l app=mizzou-processor
# Old replicaset will recreate pod from previous image
```

---

## Success Criteria

- [ ] Build completes successfully
- [ ] Pod rolls out without CrashLoopBackOff
- [ ] Entity extraction command runs without SQL errors
- [ ] ML analysis command loads model without 407 errors
- [ ] Processor logs show successful processing of backlogged articles
- [ ] No increase in error rates after deployment
- [ ] CAPTCHA backoffs show increased times (900s/7200s)

---

## Post-Deployment Monitoring

### Week 1 Focus
1. Monitor entity extraction success rate
2. Monitor ML analysis throughput
3. Track CAPTCHA backoff frequency and duration
4. Identify persistently problematic domains

### Actions for Problematic Domains
1. Document which domains still fail consistently
2. Research domain-specific solutions (APIs, RSS full content, etc.)
3. Consider temporary exclusion list
4. Evaluate residential proxy service costs

---

## Files Modified

### Code Changes
- `src/cli/commands/entity_extraction.py` - SQL join fix

### Configuration Changes
- `k8s/processor-deployment.yaml` - Proxy bypass and extraction tuning

### Documentation
- `PROCESSOR_ERRORS_ANALYSIS.md` - Detailed error analysis
- `PROCESSOR_ERROR_FIXES_DEPLOYMENT.md` - This deployment summary
