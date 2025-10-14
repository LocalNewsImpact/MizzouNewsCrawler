# Fix: 404/410 Responses Triggering Unnecessary Fallback Methods

**Date**: October 14, 2025  
**Commit**: 615f8f9  
**Issue**: 404/410 responses were allowing fallback to BeautifulSoup and Selenium

---

## Problem

When the primary extraction method (newspaper4k) encountered a 404 or 410 response, it correctly raised a `NotFoundError` exception to indicate the URL is permanently missing. However, the exception handling in `extract_content()` was catching this exception with a generic `except Exception` handler, allowing the system to proceed with BeautifulSoup and Selenium fallbacks.

### Problematic Code Flow

```python
def extract_content(self, url: str, html: str = None, metrics: Optional[object] = None):
    # Try newspaper4k first
    try:
        newspaper_result = self._extract_with_newspaper(url, html)
        # ... process result
    except Exception as e:  # ❌ Catches NotFoundError and RateLimitError!
        logger.info(f"newspaper4k extraction failed for {url}: {e}")
        # ... continues to try BeautifulSoup and Selenium
```

### Impact

1. **Wasted Resources**: Dead URLs (404/410) triggered 3 extraction attempts instead of 1
2. **Unnecessary Load**: Rate-limited domains received additional requests via BS/Selenium
3. **Slower Processing**: Each failed extraction attempt added ~5-10 seconds
4. **Misleading Logs**: Logs showed "attempting BeautifulSoup fallback" for URLs that don't exist

### Example Scenario

```
URL: https://example.com/article/12345 (returns 404)

OLD BEHAVIOR:
1. newspaper4k: 404 → NotFoundError raised
2. ❌ Generic Exception handler catches it
3. BeautifulSoup: Attempts extraction → fails (still 404)
4. Selenium: Attempts extraction → fails (still 404)
Total: 3 requests to dead URL, ~15-20 seconds wasted

NEW BEHAVIOR:
1. newspaper4k: 404 → NotFoundError raised
2. ✅ Explicit NotFoundError handler re-raises immediately
3. No BeautifulSoup or Selenium attempts
Total: 1 request to dead URL, stops immediately
```

---

## Root Cause

The issue was in the exception handling order in `src/crawler/__init__.py` line ~1130. Python evaluates `except` clauses in order, and `NotFoundError` is a subclass of `Exception`, so it was caught by the generic handler first:

```python
# Exception hierarchy
Exception
└── NotFoundError      # Custom exception for 404/410
└── RateLimitError     # Custom exception for rate limiting/bot protection
```

Both custom exceptions inherit from `Exception`, so they were caught by the generic `except Exception` block before they could be re-raised.

---

## Solution

Added **explicit exception handlers** for `NotFoundError` and `RateLimitError` **BEFORE** the generic `Exception` handler. These specific handlers immediately re-raise the exception to stop all fallback attempts.

### Fixed Code

```python
def extract_content(self, url: str, html: str = None, metrics: Optional[object] = None):
    # Try newspaper4k first
    try:
        newspaper_result = self._extract_with_newspaper(url, html)
        # ... process result
    except NotFoundError as e:
        # ✅ 404/410 - URL permanently missing, stop all fallback attempts
        logger.warning(f"URL not found (404/410), stopping extraction: {url}")
        if metrics:
            metrics.end_method("newspaper4k", False, str(e), {})
        raise  # Re-raise to prevent BeautifulSoup/Selenium fallback
    except RateLimitError as e:
        # ✅ Rate limiting/bot protection, stop all fallback attempts
        logger.warning(f"Rate limit/bot protection, stopping extraction: {url}")
        if metrics:
            metrics.end_method("newspaper4k", False, str(e), {})
        raise  # Re-raise to prevent BeautifulSoup/Selenium fallback
    except Exception as e:
        # ✅ Generic errors still allow fallback
        logger.info(f"newspaper4k extraction failed for {url}: {e}")
        # ... continues to try BeautifulSoup and Selenium
```

---

## Testing

### Test Case 1: 404 Response (Dead URL)

**Setup:**
- URL returns 404 Not Found
- newspaper4k raises NotFoundError

**Expected Behavior:**
- ✅ newspaper4k logs: "Permanent missing (404) for {url}; caching"
- ✅ extract_content logs: "URL not found (404/410), stopping extraction"
- ✅ No BeautifulSoup attempt logged
- ✅ No Selenium attempt logged
- ✅ Exception propagates to caller

**Verification:**
```bash
# Check logs for 404 URL extraction attempt
kubectl logs -n production <pod> | grep -A5 "404"

# Should see:
# "Permanent missing (404) for https://example.com/dead; caching"
# "URL not found (404/410), stopping extraction: https://example.com/dead"
# Should NOT see:
# "Attempting BeautifulSoup fallback"
# "Attempting Selenium fallback"
```

### Test Case 2: 410 Response (Gone)

**Setup:**
- URL returns 410 Gone
- newspaper4k raises NotFoundError

**Expected Behavior:**
- Same as Test Case 1 (410 treated identically to 404)

### Test Case 3: Rate Limit Response (429 or Bot Protection)

**Setup:**
- URL triggers rate limiting or bot protection
- newspaper4k raises RateLimitError

**Expected Behavior:**
- ✅ extract_content logs: "Rate limit/bot protection, stopping extraction"
- ✅ No BeautifulSoup attempt logged
- ✅ No Selenium attempt logged
- ✅ Exception propagates to caller

**Verification:**
```bash
# Check logs for rate-limited extraction
kubectl logs -n production <pod> | grep -A5 "rate limit"

# Should see:
# "🚫 Bot protection detected (403, ..."
# "Rate limit/bot protection, stopping extraction"
# Should NOT see:
# "Attempting BeautifulSoup fallback"
```

### Test Case 4: Generic Error (Should Still Allow Fallback)

**Setup:**
- URL returns 200 but newspaper4k fails to parse (e.g., malformed HTML)
- newspaper4k raises generic Exception

**Expected Behavior:**
- ✅ extract_content logs: "newspaper4k extraction failed for {url}: {e}"
- ✅ BeautifulSoup fallback IS attempted
- ✅ Selenium fallback IS attempted (if BS fails)

**Verification:**
```bash
# Check logs for generic error with fallback
kubectl logs -n production <pod> | grep -A10 "extraction failed"

# Should see:
# "newspaper4k extraction failed for {url}: ..."
# "Attempting BeautifulSoup fallback for missing fields"
# (If BS also fails) "Attempting Selenium fallback"
```

---

## Deployment

### Prerequisites
- Commit 615f8f9 pushed to feature/gcp-kubernetes-deployment
- All related commits included:
  - db19570: Initial 404/410 handling improvements
  - 15c831f: Article count display fixes
  - 6bd5ca9: Single-domain detection
  - 8276768: Dataset-filtered count query
  - 7b9e9a5: False positive single-domain fix
  - 9b2e035: Documentation
  - 615f8f9: This fix (404/410 fallback prevention)

### Build & Deploy

```bash
# 1. Build new processor image
gcloud builds triggers run build-processor-manual --branch=feature/gcp-kubernetes-deployment

# 2. Verify image built successfully
gcloud builds list --limit=1

# 3. Check deployment updated (Cloud Build auto-deploys)
kubectl get deployment mizzou-processor -n production -o jsonpath='{.spec.template.spec.containers[0].image}'

# 4. Verify rollout completed
kubectl rollout status deployment/mizzou-processor -n production

# 5. Update Lehigh job to new image
kubectl delete job lehigh-extraction -n production
# Edit k8s/lehigh-extraction-job.yaml: processor:615f8f9
kubectl apply -f k8s/lehigh-extraction-job.yaml
```

### Verification in Production

```bash
# Monitor new extractions for 404 handling
kubectl logs -f -n production <processor-pod> | grep -E "(404|410|stopping extraction)"

# Check extraction metrics
kubectl exec -n production deployment/mizzou-api -- python -c "
from src.models.database import DatabaseManager
from sqlalchemy import text
db = DatabaseManager()
result = db.session.execute(text('SELECT COUNT(*) FROM articles WHERE metadata->>\"http_status\" IN (\"404\", \"410\")'))
print(f'Articles with 404/410: {result.scalar()}')
db.session.close()
"

# Verify no BeautifulSoup/Selenium attempts after 404
kubectl logs -n production <processor-pod> | grep -A5 "404" | grep -c "BeautifulSoup"
# Should output: 0
```

---

## Performance Impact

### Before Fix (Per Dead URL)

| Extraction Method | Time    | Result |
|-------------------|---------|--------|
| newspaper4k       | ~5s     | 404    |
| BeautifulSoup     | ~5s     | 404    |
| Selenium          | ~10s    | 404    |
| **Total**         | **~20s**| Failed |

### After Fix (Per Dead URL)

| Extraction Method | Time    | Result |
|-------------------|---------|--------|
| newspaper4k       | ~5s     | 404    |
| **Total**         | **~5s** | Failed |

**Savings**: ~15 seconds per dead URL × thousands of articles = **significant reduction**

### Estimated Impact on Lehigh Dataset

- Lehigh has ~61 remaining articles
- Estimated 5-10% are dead URLs (404/410): ~3-6 URLs
- Savings: 3-6 URLs × 15 seconds = **45-90 seconds saved**
- Plus: Reduced load on rate-limited domain

---

## Related Commits

1. **db19570**: Initial 404/410 fixes (negative caching, dead URL TTL)
2. **615f8f9**: This fix (prevent fallback on 404/410)

Together, these commits provide comprehensive 404/410 handling:
- db19570: Cache dead URLs to avoid repeated requests
- 615f8f9: Stop fallback methods when URL is dead

---

## Edge Cases Handled

### Case 1: Server Returns 404 for Valid Articles (Temporary Outage)

**Scenario**: Server temporarily returns 404 for articles that exist

**Behavior**:
- First extraction: 404 → cached as dead (with TTL)
- After TTL expires: Cache entry removed, can retry
- If server recovers: Next extraction succeeds

**Configuration**: `dead_url_ttl` parameter (default: 3600s = 1 hour)

### Case 2: False 404 from Bot Protection

**Scenario**: Server returns 404 as bot protection (not real 404)

**Behavior**:
- newspaper4k detects bot protection signature
- Raises RateLimitError (not NotFoundError)
- Triggers CAPTCHA backoff, not dead URL caching

**Detection**: `_detect_bot_protection_in_response()` checks response body

### Case 3: 410 Gone (Permanent Removal)

**Scenario**: Article was deleted, returns 410 Gone

**Behavior**:
- Treated identically to 404
- Cached as dead URL
- No fallback attempts
- Exception propagates

---

## Monitoring

### Metrics to Track

1. **404/410 Rate**: How many articles return 404/410
   ```sql
   SELECT COUNT(*) FROM articles 
   WHERE metadata->>'http_status' IN ('404', '410')
   ```

2. **Fallback Method Usage**: Should decrease after this fix
   ```sql
   SELECT 
       metadata->>'extraction_method' as method,
       COUNT(*) as count
   FROM articles
   GROUP BY method
   ORDER BY count DESC
   ```

3. **Extraction Duration**: Average time per article should decrease
   ```sql
   SELECT AVG(
       EXTRACT(EPOCH FROM (updated_at - created_at))
   ) as avg_seconds
   FROM articles
   WHERE created_at > NOW() - INTERVAL '1 hour'
   ```

### Alerts to Configure

1. **High 404 Rate**: Alert if >20% of articles return 404/410
2. **Dead URL Cache Size**: Alert if cache grows too large (memory concern)
3. **Fallback After 404**: Alert if logs show BeautifulSoup after 404 (bug)

---

## Rollback Plan

If this fix causes issues:

```bash
# 1. Revert to previous working image
kubectl set image deployment/mizzou-processor processor=processor:9b2e035 -n production

# 2. Verify rollback
kubectl rollout status deployment/mizzou-processor -n production

# 3. Check logs
kubectl logs -n production deployment/mizzou-processor --tail=50
```

**Risk Assessment**: LOW
- Fix only affects exception handling order
- No changes to actual extraction logic
- Improves performance by avoiding unnecessary work
- Reduces load on domains (better for rate limiting)

---

## Summary

✅ **Fixed**: 404/410 responses now stop all fallback attempts immediately  
✅ **Performance**: ~15 seconds saved per dead URL  
✅ **Reliability**: Reduced load on rate-limited domains  
✅ **Code Quality**: Explicit exception handling for clarity  

**Next Steps**:
1. Deploy fix with other pending commits (8276768, 7b9e9a5)
2. Monitor 404/410 handling in production
3. Track extraction duration metrics
4. Consider adding dead URL cache eviction policy

---

**Status**: ✅ **READY FOR DEPLOYMENT**
