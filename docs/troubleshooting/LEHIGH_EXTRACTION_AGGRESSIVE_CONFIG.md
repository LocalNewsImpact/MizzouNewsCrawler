# Lehigh Valley Extraction - Aggressive Rate Limiting Configuration

## Problem Analysis

**Initial Job Results (Job 1):**
- **URLs Processed**: 149 out of 1,109 (13.3%)
- **Duration**: 5m59s
- **Rate**: ~25 articles/minute (~2.4s per article average)
- **Failure Mode**: CAPTCHA triggered after ~150 requests
- **Backoff**: 662 seconds (11 minutes)
- **Outcome**: Job completed but skipped all remaining URLs due to rate limit

**Root Cause:**
lehighvalleynews.com has aggressive bot detection that triggers CAPTCHA/rate limiting at approximately 25 requests/minute, even with reasonable 1.5-3.5 second delays between requests.

## Aggressive Configuration (Job 2)

### Batch Configuration
```yaml
--limit: 5           # 5 articles per batch (down from 20)
--batches: 250       # 250 batches total (up from 60)
Total capacity: 1,250 URLs
```

### Inter-Request Delays
```yaml
INTER_REQUEST_MIN: 8.0   # 8 seconds minimum (up from 1.5s)
INTER_REQUEST_MAX: 15.0  # 15 seconds maximum (up from 3.5s)
Average: ~11.5 seconds between requests
```

### Batch Sleep
```yaml
BATCH_SLEEP_SECONDS: 30.0  # 30 second pause between batches (new)
```

### CAPTCHA Backoff
```yaml
CAPTCHA_BACKOFF_BASE: 1800   # 30 minutes base (up from 10 min)
CAPTCHA_BACKOFF_MAX: 7200    # 120 minutes max (up from 90 min)
Exponential backoff: 30min → 60min → 120min
```

## Expected Performance

### Request Rate
- **Per-article average**: 8-15 seconds
- **Batch overhead**: 30 seconds per 5 articles
- **Effective rate**: ~3-5 articles/minute (vs. 25/min previously)
- **Reduction factor**: ~6-8x slower

### Completion Timeline
- **Total URLs**: 1,109 remaining (960 unprocessed + any new)
- **Estimated duration**: 4-6 hours for full extraction
- **Batches required**: ~222 batches (1,109 / 5)

### Resource Usage
- **CPU**: 250m-1000m (same as before)
- **Memory**: 1Gi-3Gi (same as before)
- **Network**: ~5-8 requests/minute (very conservative)

## Rate Limiting Strategy

### Preventive Measures
1. **Longer delays**: 8-15s between requests prevents rapid-fire detection
2. **Batch spacing**: 30s between batches allows site metrics to reset
3. **Smaller batches**: 5 articles reduces burst impact
4. **User agent rotation**: Already enabled in ContentExtractor

### Recovery Measures
1. **Aggressive backoff**: 30-120 minute waits if CAPTCHA detected
2. **Exponential scaling**: Each retry doubles the wait time
3. **Graceful skipping**: Rate-limited domains skipped, not failed
4. **Job continuation**: Job processes all batches, doesn't exit early

## Monitoring

### Key Metrics
```bash
# Check job progress
kubectl exec -n production deployment/mizzou-processor -- python3 -c "
from src.models.database import DatabaseManager
from sqlalchemy import text
db = DatabaseManager()
with db.get_session() as session:
    result = session.execute(text('''
        SELECT 
            status,
            COUNT(*) as count
        FROM candidate_links
        WHERE dataset_id = '3c4db976-e30f-4ba5-8b48-0b1c99902003'
        GROUP BY status
        ORDER BY status
    ''')).fetchall()
    for row in result:
        print(f'{row[0]}: {row[1]}')
"

# Check for rate limiting
kubectl logs -n production -l app=lehigh-extraction --tail=100 | grep -E "rate|CAPTCHA|backoff"

# Monitor batch progress
kubectl logs -n production -l app=lehigh-extraction --tail=20 | grep "batch"
```

### Success Indicators
- ✅ No CAPTCHA backoff messages in logs
- ✅ Steady batch progress (1 batch every 1-2 minutes)
- ✅ Articles incrementing in database
- ✅ No errors in extraction

### Failure Indicators
- ⚠️ CAPTCHA backoff messages
- ⚠️ "Skipping domain due to rate limit" warnings
- ⚠️ Job stops progressing for >10 minutes
- ⚠️ Multiple 429/503 HTTP errors

## Code Changes

### src/cli/commands/extraction.py
Added configurable batch sleep via environment variable:
```python
# Pause between batches (configurable via BATCH_SLEEP_SECONDS)
import os
batch_sleep = float(os.getenv("BATCH_SLEEP_SECONDS", "0.1"))
if batch_sleep > 0:
    print(f"   ⏸️  Waiting {batch_sleep}s before next batch...")
    time.sleep(batch_sleep)
```

### k8s/lehigh-extraction-job.yaml
Added five new environment variables for aggressive rate limiting.

## Deployment

### Job Start
```bash
kubectl delete job lehigh-extraction -n production
kubectl apply -f k8s/lehigh-extraction-job.yaml
```

### Job Monitoring
```bash
# Watch pod status
watch -n 10 'kubectl get pods -n production -l app=lehigh-extraction'

# Follow logs
kubectl logs -n production -l app=lehigh-extraction -f

# Check database progress every 5 minutes
watch -n 300 'kubectl exec -n production deployment/mizzou-processor -- python3 -c "..."'
```

### Job Cleanup
```bash
# Job auto-cleans after 24 hours (ttlSecondsAfterFinished: 86400)
# Or delete manually:
kubectl delete job lehigh-extraction -n production
```

## Future Improvements

1. **Dynamic rate adjustment**: Detect rate limiting and automatically slow down
2. **IP rotation**: Use residential proxy pool if available
3. **Time-based scheduling**: Extract during off-peak hours
4. **Domain-specific limits**: Per-domain rate limit configuration
5. **Backoff persistence**: Store backoff state across job restarts

## References

- **Job Config**: `k8s/lehigh-extraction-job.yaml`
- **Extraction Logic**: `src/cli/commands/extraction.py`
- **Rate Limiting**: `src/crawler/__init__.py` (lines 427-450)
- **Dataset ID**: `3c4db976-e30f-4ba5-8b48-0b1c99902003` (Penn-State-Lehigh)
- **Source ID**: `b9033f21-1110-4be7-aa93-15ff48bce725` (Lehigh Valley News)

---

**Job Started**: 2025-10-11 19:36:29 UTC  
**Expected Completion**: 2025-10-12 00:00:00 - 02:00:00 UTC (4-6 hours)  
**Git Commit**: df76080
