# Lehigh Valley News Bot Protection Response

## Incident Summary
**Date:** October 12, 2025  
**Issue:** Lehigh extraction job hit CAPTCHA/bot protection after only 16 articles  
**Root Cause:** Lehigh Valley News has extremely aggressive bot detection  

## Actions Taken

### 1. Bot Sensitivity Updated
- **Source:** www.lehighvalleynews.com  
- **Previous Sensitivity:** 5 (moderate/default)  
- **New Sensitivity:** 10 (maximum caution)  
- **Bot Encounters:** Incremented to 1  

### 2. Rate Limiting Configuration (EXTREME)

Updated `k8s/lehigh-extraction-job.yaml` with ultra-conservative settings:

| Parameter | Previous | New | Change |
|-----------|----------|-----|--------|
| `INTER_REQUEST_MIN` | 30s | 60s | **2x slower** - 1 minute minimum between requests |
| `INTER_REQUEST_MAX` | 45s | 120s | **2.7x slower** - 2 minutes maximum between requests |
| `CAPTCHA_BACKOFF_BASE` | 2400s (40m) | 7200s (2h) | **3x longer** - 2 hour base backoff on CAPTCHA |
| `CAPTCHA_BACKOFF_MAX` | 7200s (2h) | 21600s (6h) | **3x longer** - 6 hour maximum backoff |
| `BATCH_SLEEP_SECONDS` | 180s (3m) | 600s (10m) | **3.3x longer** - 10 minutes between batches |
| Batch Size (`--limit`) | 3 articles | 1 article | **3x smaller** - Single article per batch |
| Total Batches | 300 | 600 | 2x more batches to accommodate single-article approach |

### 3. Extraction Timeline Estimates

With the new ultra-conservative settings:

**Per Article:**
- Fetch time: 60-120 seconds (inter-request delay)
- Batch sleep: 600 seconds (10 minutes)
- **Total per article:** ~11-12 minutes

**For Remaining 579 Articles:**
- **Minimum Time:** ~106 hours (4.4 days)
- **Maximum Time:** ~116 hours (4.8 days)
- **Expected:** ~4.5 days of continuous extraction

### 4. Bot Detection Error Fixed

Identified JSON formatting error in bot_detection_events recording:
```python
# Error: {'protection_type': 'bot_protection'} 
# PostgreSQL requires proper JSON format, not Python dict string
```

This will need to be fixed in `src/utils/bot_sensitivity_manager.py` in a future update to use `json.dumps()` for proper JSON serialization.

## New Job Configuration

```yaml
command:
  - python
  - -m
  - src.cli.cli_modular
  - extract
  - --dataset
  - Penn-State-Lehigh
  - --limit
  - "1"  # Single article per batch
  - --batches
  - "600"  # 579 remaining + buffer

env:
  - name: INTER_REQUEST_MIN
    value: "60.0"
  - name: INTER_REQUEST_MAX
    value: "120.0"
  - name: CAPTCHA_BACKOFF_BASE
    value: "7200"
  - name: CAPTCHA_BACKOFF_MAX
    value: "21600"
  - name: BATCH_SLEEP_SECONDS
    value: "600.0"
  - name: DECODO_ROTATE_IP
    value: "true"
```

## Monitoring Commands

### Check extraction progress:
```bash
kubectl exec -n production mizzou-api-6c7876cb6f-47rd2 -- python -c "
from src.models.database import DatabaseManager
from sqlalchemy import text
with DatabaseManager() as db:
    result = db.session.execute(text(\"SELECT COUNT(*) FROM candidate_links WHERE dataset_id = (SELECT id FROM datasets WHERE slug = 'Penn-State-Lehigh') AND status = 'extracted'\"))
    print(f'Extracted: {result.scalar()} / 1108')
"
```

### Watch logs:
```bash
kubectl logs -n production -l app=lehigh-extraction --follow
```

### Check job status:
```bash
kubectl get job lehigh-extraction -n production
```

### Check bot sensitivity:
```bash
kubectl exec -n production mizzou-api-6c7876cb6f-47rd2 -- python -c "
from src.models.database import DatabaseManager
from sqlalchemy import text
with DatabaseManager() as db:
    result = db.session.execute(text(\"SELECT canonical_name, bot_sensitivity, bot_encounters FROM sources WHERE host = 'www.lehighvalleynews.com'\"))
    for row in result:
        print(f'{row[0]}: Sensitivity={row[1]}, Encounters={row[2]}')
"
```

## Expected Behavior

With these extreme settings:
- **1 article every 11-12 minutes**
- **10 minute pause between batches**
- **2-6 hour backoff if CAPTCHA detected**
- **IP rotation on every request (Decodo)**
- **User agent rotation every 4 requests**

This should be slow enough to avoid bot detection patterns while still making progress.

## Status

- ✅ Bot sensitivity updated to level 10
- ✅ Rate limiting increased to extreme levels
- ✅ Batch size reduced to 1 article
- ✅ Job restarted with new configuration
- ⏳ Extraction in progress (ETA: ~4.5 days)
- 📊 Current progress: 528/1108 extracted (48%)
- 🎯 Remaining: 579 articles

## Future Improvements

1. **Fix JSON serialization** in `bot_sensitivity_manager.py` to properly record bot detection events
2. **Consider adding random delays** between batches (e.g., 8-12 minutes instead of fixed 10)
3. **Monitor for sustained success** - if we go 100+ articles without detection, consider slightly relaxing limits
4. **Document Lehigh Valley News** in `KNOWN_SENSITIVE_PUBLISHERS` with sensitivity level 10
