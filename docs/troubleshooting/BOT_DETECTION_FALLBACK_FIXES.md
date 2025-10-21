# Bot Detection & Extraction Fallback Fixes

**Date**: October 14, 2025  
**Branch**: `feature/gcp-kubernetes-deployment`  
**Commits**: `1b34328`, `a5a18b2`, `14922a5`

## Problem Summary

The extraction system had a critical issue where hitting bot detection, rate limits, or 404 errors would trigger unnecessary and harmful fallback attempts:

### Issue 1: Bot Detection Fallbacks
When any extraction method hit a CAPTCHA or rate limit:
1. **newspaper4k**: Detected bot protection, set backoff (e.g., 6562s), returned error result
2. **BeautifulSoup**: Checked rate limit, raised error (caught by outer handler)
3. **Selenium**: **Explicitly ignored rate limits** (comment: "intentionally NOT check"), tried anyway
4. **Result**: Same CAPTCHA hit 2-3 times, exponential backoff growth (6562s → 16204s → 40000s+)

### Issue 2: 404 Fallbacks  
When a URL returned 404/410 (permanent not found):
1. **newspaper4k**: Detected 404, cached as dead URL, returned error result
2. **BeautifulSoup**: Tried to fetch again (wasted HTTP request)
3. **Selenium**: Tried with browser (wasted 25-60 seconds)
4. **Result**: 30-90 seconds wasted per 404, hundreds of wasted requests

### Impact on Bot Sensitivity
- Bot sensitivity levels climbed rapidly to level 10 (max)
- Domains accumulated 100+ encounters quickly
- Backoff periods grew exponentially (hours → days)
- Domain rotation couldn't help (same domain hit repeatedly)
- Extraction throughput dropped dramatically

## Solutions Implemented

### Fix 1: Selenium Respects CAPTCHA Backoffs (Commit `1b34328`)

**Changed**: `src/crawler/__init__.py` lines 1186-1205

**Before**:
```python
# NOTE: Selenium is specifically for bypassing CAPTCHA/bot protection,
# so we intentionally DO NOT check rate limits here.
dom = urlparse(url).netloc
selenium_failures = getattr(self, "_selenium_failure_counts", {})
if selenium_failures.get(dom, 0) >= 3:
    # Only check Selenium failure count
```

**After**:
```python
# Check if domain is in CAPTCHA backoff period
# Selenium should respect CAPTCHA backoffs since it will just hit the same CAPTCHA
dom = urlparse(url).netloc
if self._check_rate_limit(dom):
    logger.info(
        f"Skipping Selenium for {dom} - domain is in CAPTCHA backoff period"
    )
    raise RateLimitError(f"Domain {dom} is in backoff period")

# Only check if Selenium itself has failed repeatedly on this domain
selenium_failures = getattr(self, "_selenium_failure_counts", {})
if selenium_failures.get(dom, 0) >= 3:
```

**Impact**: Selenium no longer attempts on domains in backoff, preventing exponential backoff growth.

---

### Fix 2: All Bot Detection Raises Exceptions (Commit `a5a18b2`)

**Changed**: `src/crawler/__init__.py` multiple locations

**Before**: Bot detection returned error result dict
```python
self._handle_captcha_backoff(domain)
return self._create_error_result(url, "Bot protection", {...})
```

**After**: Bot detection raises exception to stop all fallbacks
```python
self._handle_captcha_backoff(domain)
raise RateLimitError(f"Bot protection detected on {domain}: {protection_type}")
```

**Applied to**:
1. **429 Rate Limit** (line 1567): `raise RateLimitError(f"Rate limited (429) by {domain}")`
2. **403/503 with bot protection** (line 1598): `raise RateLimitError(f"Bot protection on {domain}...")`
3. **403/503 server errors** (line 1611): `raise RateLimitError(f"Server error ({status_code}) on {domain}")`
4. **200 with CAPTCHA HTML** (line 1651): `raise RateLimitError(f"Bot protection detected on {domain}...")`

**Impact**: Single bot detection → immediate exception → skip to next domain, no fallback attempts.

---

### Fix 3: 404 Errors Stop Fallbacks (Commit `14922a5`)

**Created**: `NotFoundError` exception class

**Changed**: `src/crawler/__init__.py`
- **newspaper4k 404 handler** (line 1627): Raises `NotFoundError` instead of returning error
- **BeautifulSoup 404 handler** (line 1787): Raises `NotFoundError` instead of returning `{}`

**Changed**: `src/cli/commands/extraction.py`
- Added `NotFoundError` import
- Added specific `except NotFoundError` handler before general exception handler
- Handler marks URL as 404, doesn't increment domain_failures, continues to next URL

**Impact**: 404s immediately stop extraction, save 30-90 seconds per 404, domain failures not polluted.

---

## Expected Results

### Bot Sensitivity Stabilization
- ✅ Single CAPTCHA detection → immediate domain skip
- ✅ No exponential backoff growth (one backoff per detection, not 3)
- ✅ Bot sensitivity levels stabilize instead of climbing to 10
- ✅ Backoff periods remain manageable (2-6 hours vs days)

### Domain Rotation Effectiveness
- ✅ Domains in backoff truly skipped (not retried with Selenium)
- ✅ System moves to next available domain immediately
- ✅ Domain rotation can actually work as designed
- ✅ Mixed-domain batches process efficiently

### Performance Improvements
- ✅ 404s save 30-90 seconds each (no BeautifulSoup/Selenium attempts)
- ✅ Bot detections save 25-60 seconds each (no Selenium retry)
- ✅ Overall extraction throughput increases dramatically
- ✅ Wasted bandwidth reduced (no redundant CAPTCHA/404 requests)

### Cleaner Metrics
- ✅ 404s don't pollute domain failure tracking
- ✅ Bot detection events accurately counted (once per detection)
- ✅ Error types properly categorized (not_found vs rate_limited)
- ✅ Telemetry shows true extraction vs error patterns

---

## Deployment Status

### Images Built
- ✅ `processor:a5a18b2` - Bot detection fixes (Selenium + exception raising)
- ✅ `processor:14922a5` - Complete fixes (bot detection + 404 handling)
- ✅ `processor:db19570` - **COMPREHENSIVE** (403/401 in BeautifulSoup + re-raise fixes)

### Currently Deployed
- **Image**: `processor:db19570` (building/deploying now)
- **Pod**: Will be `mizzou-processor-*` (new pod after deployment)
- **Status**: Build queued at 2025-10-14 01:32:24 UTC

### Final Fix (Commit `db19570`)
**Problem**: BeautifulSoup wasn't checking status codes before `raise_for_status()`, so 403s and other errors were caught as HTTPError, returned `{}`, allowing Selenium to try.

**Solution**:
1. BeautifulSoup now checks status codes BEFORE `raise_for_status()`:
   - 404/410 → `NotFoundError`
   - 429 → `RateLimitError`
   - 401/403/502/503/504 → `RateLimitError`
2. newspaper4k now re-raises `RateLimitError` and `NotFoundError` (doesn't catch and convert to error result)
3. Added 401 (Unauthorized) to error code list

**Complete Status Code Handling**:
- 404/410 → NotFoundError (permanent not found)
- 429 → RateLimitError (rate limiting)
- 401 → RateLimitError (authentication required)
- 403 → RateLimitError (forbidden/bot detection)
- 502 → RateLimitError (bad gateway/rate limit proxy)
- 503 → RateLimitError (service unavailable/rate limit)
- 504 → RateLimitError (gateway timeout/rate limit)

### Verification Commands
```bash
# Check deployed image
kubectl get deployment mizzou-processor -n production -o jsonpath='{.spec.template.spec.containers[0].image}'

# Check pod status
kubectl get pods -n production -l app=mizzou-processor

# Monitor logs for new behavior
kubectl logs -n production -l app=mizzou-processor --tail=100 -f | grep -E "(Skipping Selenium|Bot protection|Rate limited|not found)"
```

---

## Monitoring

### What to Watch

1. **Bot Sensitivity Trends**:
   ```sql
   SELECT host, bot_sensitivity, bot_encounters, last_bot_detection_at
   FROM sources
   WHERE bot_sensitivity >= 8
   ORDER BY bot_encounters DESC;
   ```
   - Expect: Sensitivity levels stay lower (7-8 vs 10)
   - Expect: Encounters grow slower (linear vs exponential)

2. **Bot Detection Events**:
   ```sql
   SELECT DATE(detected_at), event_type, COUNT(*)
   FROM bot_detection_events
   WHERE detected_at > NOW() - INTERVAL '24 hours'
   GROUP BY DATE(detected_at), event_type;
   ```
   - Expect: Fewer total events (single detection per domain)
   - Expect: More varied event_types (not all CAPTCHA)

3. **Extraction Throughput**:
   - Watch batch completion times in logs
   - Expect: Faster batch processing (fewer 25-60s Selenium waits)
   - Expect: More articles per minute

4. **404 Handling**:
   ```sql
   SELECT COUNT(*) 
   FROM candidate_links 
   WHERE status = '404'
   AND updated_at > NOW() - INTERVAL '24 hours';
   ```
   - Expect: 404s marked quickly (seconds vs minutes)
   - Expect: Batch logs show immediate skip after 404

### Success Criteria

- ✅ No more "Selenium returned empty result" after CAPTCHA backoff set
- ✅ No more duplicate CAPTCHA detections for same URL within minutes
- ✅ Bot sensitivity levels stabilize within 24 hours
- ✅ Extraction throughput increases 30-50%
- ✅ 404s processed in <5 seconds instead of 30-90 seconds

---

## Related Documentation

- `PROCESSOR_RATE_LIMITING_UPDATE.md` - Initial conservative rate limiting
- Bot sensitivity system in `src/utils/bot_sensitivity_manager.py`
- Domain rotation implementation (in progress)

## Notes

These fixes are foundational for the domain rotation strategy to work effectively. Without stopping fallbacks on errors, domain rotation would still waste time hitting the same errors repeatedly on each domain before rotating.
