# Aggressive Rate Limiting Applied System-Wide

## Summary

Applied aggressive rate limiting configuration to both the Lehigh extraction job and the main processor deployment to prevent CAPTCHA/rate limiting triggers on aggressive news sites.

## Configuration Changes

### Rate Limiting Parameters

| Parameter | Previous | New | Change |
|-----------|----------|-----|--------|
| INTER_REQUEST_MIN | 2.0s | 8.0s | +300% |
| INTER_REQUEST_MAX | 4.5s | 15.0s | +233% |
| CAPTCHA_BACKOFF_BASE | 900s (15min) | 1800s (30min) | +100% |
| CAPTCHA_BACKOFF_MAX | 7200s (120min) | 7200s (120min) | No change |
| BATCH_SLEEP_SECONDS | 0.1s | 30.0s | **NEW** |

### Expected Impact

**Request Rate:**
- **Previous**: ~15-25 requests/minute
- **New**: ~3-5 requests/minute
- **Reduction**: 5-8x slower

**Processing Speed:**
- Extraction: 5-8 hours per 1,000 URLs (vs. 1-2 hours)
- Verification: Minimal impact (usually not rate limited)
- Analysis: No change (local processing)

## Affected Components

### 1. Lehigh Extraction Job
**File**: `k8s/lehigh-extraction-job.yaml`

**Batch Configuration:**
- Articles per batch: 5 (down from 20)
- Total batches: 250 (up from 60)
- Batch sleep: 30 seconds between batches

**Status**: ✅ Deployed and running (batch 4+)

### 2. Main Processor Deployment
**File**: `k8s/processor-deployment.yaml`

**Batch Configuration:**
- Uses EXTRACTION_BATCH_SIZE: 20 (from env var)
- Batch sleep: 30 seconds between batches
- Processes up to 5 batches per cycle (100 URLs)

**Status**: 🔄 Building (image: 3193752)

**Deployment**: After build completes:
```bash
# Promote release
gcloud deploy releases promote \
  --release=processor-3193752 \
  --delivery-pipeline=mizzou-news-crawler \
  --region=us-central1

# Verify deployment
kubectl rollout status deployment/mizzou-processor -n production
kubectl get pods -n production -l app=mizzou-processor

# Check rate limiting in logs
kubectl logs -n production -l app=mizzou-processor --tail=100 | grep -E "CAPTCHA|rate|backoff"
```

## Code Changes

### src/cli/commands/extraction.py (Lines 179-187)
Added configurable batch sleep:
```python
# Pause between batches (configurable via BATCH_SLEEP_SECONDS)
import os
batch_sleep = float(os.getenv("BATCH_SLEEP_SECONDS", "0.1"))
if batch_sleep > 0:
    print(f"   ⏸️  Waiting {batch_sleep}s before next batch...")
    time.sleep(batch_sleep)
```

This change allows both the job and continuous processor to pause between batches via environment variable.

## Rationale

### Problem
lehighvalleynews.com triggered CAPTCHA after ~150 requests at 25 req/min, causing the extraction job to skip 960 remaining URLs. This aggressive bot detection is becoming more common across news sites.

### Solution
Dramatically reduce request rate to appear more human-like:
- **8-15 second delays** between requests (vs. 2-4.5s)
- **30 second pauses** between batches of 5-20 articles
- **30-120 minute backoffs** if CAPTCHA detected anyway

### Trade-offs
- **Slower extraction**: 5-8 hours for 1,000 URLs instead of 1-2 hours
- **Better reliability**: Avoid CAPTCHA/rate limiting entirely
- **Lower risk**: Sites less likely to permanently block our IPs
- **Minimal impact**: Continuous processor runs 24/7, speed less critical

## Monitoring

### Key Metrics to Watch

1. **CAPTCHA Triggers**
   ```bash
   kubectl logs -n production -l app=mizzou-processor --tail=500 | grep "CAPTCHA backoff" | wc -l
   ```
   - **Target**: 0 (no CAPTCHA triggers)
   - **Alert**: >3 per hour indicates settings still too aggressive

2. **Rate Limit Skips**
   ```bash
   kubectl logs -n production -l app=mizzou-processor --tail=500 | grep "rate limited" | wc -l
   ```
   - **Target**: 0 (no skipped domains)
   - **Alert**: >5 per cycle indicates ongoing rate limiting

3. **Extraction Progress**
   ```bash
   kubectl exec -n production deployment/mizzou-processor -- python3 -c "
   from src.models.database import DatabaseManager
   from sqlalchemy import text
   db = DatabaseManager()
   with db.get_session() as session:
       ready = session.execute(text(
           'SELECT COUNT(*) FROM candidate_links WHERE status = \\'article\\''
       )).scalar()
       extracted = session.execute(text(
           'SELECT COUNT(*) FROM articles WHERE created_at > NOW() - INTERVAL \\'1 hour\\''
       )).scalar()
       print(f'Ready: {ready}, Extracted last hour: {extracted}')
   "
   ```
   - **Target**: 20-40 articles/hour (vs. 100-200 previously)
   - **Alert**: <10 articles/hour indicates stalling

4. **Processor Health**
   ```bash
   kubectl get pods -n production -l app=mizzou-processor
   kubectl logs -n production -l app=mizzou-processor --tail=50
   ```
   - Check for restarts, errors, or crashes
   - Verify continuous polling every 60 seconds

## Rollback Plan

If aggressive settings cause issues (processor too slow, queues backing up):

### Quick Rollback
```bash
# Revert to previous settings
git revert HEAD~2
git push origin feature/gcp-kubernetes-deployment

# Rebuild processor
gcloud builds triggers run build-processor-manual --branch=feature/gcp-kubernetes-deployment

# Promote (after build completes)
gcloud deploy releases promote --release=processor-<new-sha> ...
```

### Partial Rollback (Keep Some Conservative Settings)
Edit `k8s/processor-deployment.yaml`:
```yaml
# More balanced settings
- name: INTER_REQUEST_MIN
  value: "4.0"    # 4 seconds (between aggressive 8s and old 2s)
- name: INTER_REQUEST_MAX
  value: "8.0"    # 8 seconds (between aggressive 15s and old 4.5s)
- name: BATCH_SLEEP_SECONDS
  value: "10.0"   # 10 seconds (between aggressive 30s and old 0.1s)
```

## Performance Expectations

### Continuous Processor (24/7 Operation)

**Previous Performance:**
- 5 batches × 20 articles = 100 URLs per cycle
- ~2-3 minutes per cycle
- ~2,000-3,000 articles per day

**New Performance:**
- 5 batches × 20 articles = 100 URLs per cycle
- ~8-12 minutes per cycle (4x slower)
- ~500-1,000 articles per day

**Impact Assessment:**
- ✅ Still adequate for normal daily volume (~200-500 new articles)
- ✅ Prevents queue buildup for most sources
- ⚠️ May struggle with sudden spikes (>1,000 articles at once)
- ✅ Can run dedicated jobs for large datasets (like Lehigh)

### Dedicated Extraction Jobs

**Job Configuration:**
- Small batches: 5 articles
- Many batches: 250 total (1,250 capacity)
- Long delays: 8-15s per request + 30s per batch

**Timeline for 1,000 URLs:**
- Best case: ~4 hours (10s avg/request + 30s/batch)
- Worst case: ~8 hours (15s avg/request + 30s/batch)
- With CAPTCHA triggers: Add 30-120 minutes per trigger

## Next Steps

1. **Monitor Lehigh job** for next 2-4 hours
   - Should complete ~1,000 URLs without CAPTCHA
   - Check progress every hour

2. **Deploy processor update** once build completes
   - Promote release
   - Monitor for first hour
   - Check CAPTCHA/rate limit logs

3. **Validate performance** over 24 hours
   - Track extraction rates
   - Monitor queue depths
   - Check for CAPTCHA triggers

4. **Adjust if needed** based on results
   - Can fine-tune delays if too aggressive
   - Can relax settings if no CAPTCHA seen

## References

- **Lehigh Config**: `LEHIGH_EXTRACTION_AGGRESSIVE_CONFIG.md`
- **Job Manifest**: `k8s/lehigh-extraction-job.yaml`
- **Processor Deployment**: `k8s/processor-deployment.yaml`
- **Extraction Logic**: `src/cli/commands/extraction.py`
- **Rate Limit Code**: `src/crawler/__init__.py`

---

**Applied**: 2025-10-11 19:42 UTC  
**Commits**: df76080 (Lehigh job), 3193752 (processor deployment)  
**Status**: Lehigh job running, processor building
