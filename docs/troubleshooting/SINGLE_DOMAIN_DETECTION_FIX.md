# Single-Domain Detection Fix

**Date**: October 14, 2025  
**Commit**: 7b9e9a5  
**Issue**: False positive single-domain detection causing unnecessary long pauses

## Problem

The mizzou-processor was incorrectly triggering "single-domain batch" long pauses (328s) even when processing multi-domain datasets. This occurred when:

1. Multiple domains were available in the work queue
2. Most domains were rate-limited and skipped (e.g., 7 domains skipped)
3. Only 1 article from 1 domain was actually processed

### Example Log (Before Fix):
```
2025-10-14 14:32:23,505 [INFO] Article extraction (207 pending, 5 batches) | ⚠️ 7 domains skipped due to rate limits
2025-10-14 14:32:23,506 [INFO] Batch 1: {'processed': 1, 'skipped_domains': 7, 'domains_processed': ['www.koamnewsnow.com'], ...}
2025-10-14 14:32:23,506 [INFO] ⏸️ Single-domain batch - waiting 328s...
```

**Problem**: The system is waiting 328 seconds even though 7 other domains are available (just temporarily rate-limited).

## Root Cause

The single-domain detection logic only checked `unique_domains <= 1` (number of domains that were actually processed), without considering whether other domains existed but were skipped due to rate limiting.

### Old Logic (Incorrect):
```python
unique_domains = len(set(domains_processed)) if domains_processed else 0

needs_long_pause = (
    same_domain_consecutive >= max_same_domain or unique_domains <= 1
)
```

This incorrectly treated any batch that processed articles from only 1 domain as a "single-domain dataset", even if:
- Multiple domains were available in the queue
- Those domains were just temporarily rate-limited
- Domain rotation was working correctly

## Solution

Check `skipped_domains` count before applying single-domain logic. Only treat as a true single-domain dataset if:
- `unique_domains <= 1` (only processed 1 domain), **AND**
- `skipped_domains == 0` (no other domains were available)

### New Logic (Correct):
```python
unique_domains = len(set(domains_processed)) if domains_processed else 0
skipped_domains = result.get('skipped_domains', 0)

is_single_domain_dataset = unique_domains <= 1 and skipped_domains == 0
needs_long_pause = (
    same_domain_consecutive >= max_same_domain or is_single_domain_dataset
)
```

### Updated Logging:
```python
elif unique_domains > 1 or skipped_domains > 0:
    short_pause = float(os.getenv("INTER_BATCH_MIN_PAUSE", "5.0"))
    if skipped_domains > 0:
        print(
            f"   ✓ Multiple domains available "
            f"({skipped_domains} rate-limited) - "
            f"minimal {short_pause:.0f}s pause"
        )
    else:
        print(
            f"   ✓ Rotated through {unique_domains} domains - "
            f"minimal {short_pause:.0f}s pause"
        )
    time.sleep(short_pause)
```

## Impact

### Before Fix:
- **Scenario**: 1 article processed, 7 domains skipped
- **Behavior**: Long pause (328s with jitter)
- **Message**: `⏸️ Single-domain batch - waiting 328s...`
- **Problem**: Unnecessary delay when domains will become available soon

### After Fix:
- **Scenario**: 1 article processed, 7 domains skipped
- **Behavior**: Short pause (5s)
- **Message**: `✓ Multiple domains available (7 rate-limited) - minimal 5s pause`
- **Benefit**: Continues processing quickly as rate limits expire

### True Single-Domain Dataset (e.g., Lehigh):
- **Scenario**: 3 articles processed, 0 domains skipped (all from same domain)
- **Behavior**: Long pause (420s with jitter)
- **Message**: `⏸️ Single-domain dataset - waiting 462s...`
- **Benefit**: Respects bot sensitivity, prevents CAPTCHA

## Testing

### Test Case 1: Multi-Domain with Rate Limiting (Fixed Scenario)
```
Result: {'processed': 1, 'skipped_domains': 7, 'domains_processed': ['www.koamnewsnow.com']}
Expected: Short pause (5s)
Reason: Multiple domains available (7 rate-limited)
```

### Test Case 2: True Single-Domain Dataset (Lehigh)
```
Result: {'processed': 3, 'skipped_domains': 0, 'domains_processed': ['www.lv.psu.edu', 'www.lv.psu.edu', 'www.lv.psu.edu']}
Expected: Long pause (420s + jitter)
Reason: Single-domain dataset
```

### Test Case 3: Multi-Domain Rotation Working
```
Result: {'processed': 10, 'skipped_domains': 0, 'domains_processed': ['domain1.com', 'domain2.com', 'domain3.com']}
Expected: Short pause (5s)
Reason: Rotated through 3 domains
```

### Test Case 4: Same Domain Hit Repeatedly
```
Result: {'processed': 3, 'skipped_domains': 0, 'domains_processed': ['domain1.com', 'domain1.com', 'domain1.com'], 'same_domain_consecutive': 4}
Expected: Long pause (420s + jitter)
Reason: Same domain hit 4 times (exhausted rotation)
```

## Deployment

1. **Build new processor image** with commit 7b9e9a5:
   ```bash
   gcloud builds triggers run build-processor-manual --branch=feature/gcp-kubernetes-deployment
   ```

2. **Deployment updates automatically** via Cloud Build `force-processor-update` step

3. **Verify fix** in mizzou-processor logs:
   ```bash
   kubectl logs -f deployment/mizzou-processor -n production
   ```
   
   Look for:
   - `✓ Multiple domains available (X rate-limited) - minimal 5s pause` when domains are skipped
   - `⏸️ Single-domain dataset - waiting Xs...` only for true single-domain datasets

## Related Fixes

This fix builds on previous batch sleep improvements:

1. **Commit 6bd5ca9**: Added single-domain detection for datasets like Lehigh
2. **Commit 98d2733**: Fixed article count accuracy with session cleanup
3. **Commit 8276768**: Fixed article count query to filter by dataset
4. **Commit 7b9e9a5**: Fixed false positive single-domain detection (this fix)

## Files Changed

- `src/cli/commands/extraction.py`:
  - Lines 238-254: Updated single-domain detection logic
  - Lines 275-282: Updated reason message
  - Lines 284-299: Enhanced logging for rate-limited scenarios

## Success Criteria

- ✅ Multi-domain datasets with rate-limited domains: Short pause (5s)
- ✅ True single-domain datasets (Lehigh): Long pause (420s)
- ✅ Same domain hit repeatedly: Long pause (420s)
- ✅ Multi-domain rotation working: Short pause (5s)
- ✅ Clear logging explaining pause reason
- ✅ No unnecessary delays in multi-domain processing
