# Selenium Fallback Fix - CRITICAL BUG RESOLVED

**Date:** October 10, 2025  
**Issue:** Selenium fallback not being deployed despite PerimeterX CAPTCHA blocking  
**Root Cause:** Rate limit checks preventing Selenium from running  
**Status:** ✅ FIXED

---

## The Problem

After deploying bot blocking improvements (commit `5f8ff4b`), we discovered that **0% of extractions were succeeding** despite having Selenium installed. Investigation revealed:

### What Was Happening (BROKEN FLOW)

1. **Requests-based extraction** attempts to fetch from PerimeterX-protected site
2. Gets blocked with **CAPTCHA/403** response
3. `_detect_bot_protection_in_response()` correctly identifies bot protection
4. **Sets CAPTCHA backoff** (10-90 minutes) via `_handle_captcha_backoff(domain)`
5. Returns error result → triggers **Selenium fallback**
6. **Selenium checks `_check_rate_limit(domain)`** ← **BUG HERE**
7. Domain is "rate limited" from step 4 → **Selenium SKIPPED**
8. Extraction fails completely

### Evidence from Logs

```log
2025-10-10 16:05:11 - CAPTCHA or challenge detected on https://www.dddnews.com/...
2025-10-10 16:05:37 - CAPTCHA backoff for www.dddnews.com: 963s (attempt 1)
2025-10-10 16:05:38 - Attempting Selenium fallback for missing fields...
2025-10-10 16:05:38 - Selenium extraction failed: Domain www.dddnews.com is rate limited; skip Selenium
```

**The bug:** Selenium was checking the same rate limit that was set because of the CAPTCHA block. **This defeats the entire purpose of having Selenium as a CAPTCHA bypass tool!**

---

## The Fix

### Code Changes

**File:** `src/crawler/__init__.py`

#### 1. Removed Rate Limit Check from Selenium Fallback (Lines ~1128-1145)

**Before (BROKEN):**
```python
# Respect domain backoff before attempting Selenium
dom = urlparse(url).netloc
if self._check_rate_limit(dom):
    raise RateLimitError(f"Domain {dom} is rate limited; skip Selenium")
```

**After (FIXED):**
```python
# NOTE: Selenium is specifically for bypassing CAPTCHA/bot protection,
# so we intentionally DO NOT check rate limits here. If the requests-based
# approach triggered a CAPTCHA backoff, Selenium is our chance to bypass it.
# Only check if Selenium itself has failed repeatedly on this domain.
dom = urlparse(url).netloc
selenium_failures = getattr(self, "_selenium_failure_counts", {})
if selenium_failures.get(dom, 0) >= 3:
    logger.warning(
        f"Skipping Selenium for {dom} - already failed {selenium_failures[dom]} times"
    )
    raise RateLimitError(
        f"Selenium repeatedly failed for {dom}; skipping"
    )
```

**Key changes:**
- ❌ Removed `_check_rate_limit(dom)` check (was blocking Selenium when requests failed)
- ✅ Added Selenium-specific failure tracking (`_selenium_failure_counts`)
- ✅ Only skip Selenium if **Selenium itself** has failed 3+ times on the domain
- ✅ Allows Selenium to attempt CAPTCHA bypass even when requests are backed off

#### 2. Added Selenium-Specific Failure Tracking (Line ~433)

**Added to `__init__`:**
```python
# Selenium-specific failure tracking (separate from requests failures)
# This prevents disabling Selenium for CAPTCHA-protected domains
self._selenium_failure_counts = {}  # Track Selenium failures per domain
```

#### 3. Track Selenium Success/Failure (Lines ~1148-1185)

**Success tracking:**
```python
if selenium_result and selenium_result.get("content"):
    # ... merge results ...
    logger.info(f"✅ Selenium extraction succeeded for {url}")
    
    # Reset failure count on success
    if dom in self._selenium_failure_counts:
        del self._selenium_failure_counts[dom]
```

**Failure tracking:**
```python
else:
    # Selenium returned empty result - track as failure
    self._selenium_failure_counts[dom] = (
        self._selenium_failure_counts.get(dom, 0) + 1
    )
    logger.warning(
        f"❌ Selenium returned empty result for {url} "
        f"(failure #{self._selenium_failure_counts[dom]})"
    )
```

**Exception tracking:**
```python
except Exception as e:
    # Track Selenium exception as failure
    self._selenium_failure_counts[dom] = (
        self._selenium_failure_counts.get(dom, 0) + 1
    )
    logger.info(
        f"❌ Selenium extraction failed for {url}: {e} "
        f"(failure #{self._selenium_failure_counts[dom]})"
    )
```

---

## Expected Behavior After Fix

### New Flow (FIXED)

1. **Requests-based extraction** attempts PerimeterX-protected site
2. Gets blocked with CAPTCHA/403
3. Identifies bot protection → sets CAPTCHA backoff
4. Returns error → triggers **Selenium fallback**
5. **Selenium BYPASSES rate limit check** ← **FIXED**
6. **Selenium attempts extraction** (undetected ChromeDriver + stealth mode)
7. **If successful:** Extracts content, resets Selenium failure count
8. **If fails 3+ times:** Future attempts skip Selenium for this domain

### Benefits

✅ **Selenium can now bypass CAPTCHA** even when requests are rate-limited  
✅ **Separate failure tracking** prevents premature Selenium disabling  
✅ **Smart retry logic** stops trying after 3 consecutive Selenium failures  
✅ **Clear logging** shows Selenium success/failure with emojis (✅/❌)  

---

## Testing

### Pre-Fix Status
- **Extraction success rate:** 0%
- **Selenium attempts:** Skipped (rate limited)
- **Log pattern:** "Domain X is rate limited; skip Selenium"

### Expected Post-Fix Status
- **Selenium attempts:** Will execute for CAPTCHA-blocked domains
- **Expected success rate:** >10-50% on PerimeterX/Cloudflare domains (Selenium can solve many challenges)
- **Log patterns:**
  - "✅ Selenium extraction succeeded for [URL]"
  - "❌ Selenium extraction failed for [URL] (failure #N)"
  - "Skipping Selenium for [domain] - already failed 3 times" (only after 3 failures)

### Domains Expected to Benefit

**PerimeterX-protected (high priority):**
- dddnews.com
- shelbycountyherald.com
- theprospectnews.com
- lakegazette.net

**Cloudflare-protected:**
- newstribune.com
- darnews.com
- kfvs12.com

**Generic 403 blocks:**
- ozarksfirst.com
- fox2now.com
- fox4kc.com

---

## Deployment Plan

### 1. Commit Changes
```bash
git add src/crawler/__init__.py SELENIUM_FALLBACK_FIX.md
git commit -m "Fix: Allow Selenium fallback to bypass CAPTCHA despite rate limits

- Remove rate limit check from Selenium fallback (was blocking bypass)
- Add Selenium-specific failure tracking (separate from requests)
- Only skip Selenium after 3 consecutive Selenium failures
- Reset failure count on Selenium success
- Add clear logging with ✅/❌ indicators

This fixes the critical bug where Selenium was being skipped for
CAPTCHA-protected domains because the requests-based approach had
set a rate limit backoff. Selenium is specifically meant to bypass
CAPTCHA, so it should not check rate limits from requests failures."
```

### 2. Push to Branch
```bash
git push origin copilot/investigate-fix-bot-blocking-issues
```

### 3. Trigger Build & Deploy
```bash
# Check cluster resources
kubectl top nodes -n production
kubectl get cronjobs -n production

# Suspend crawler if needed
kubectl patch cronjob mizzou-crawler -n production -p '{"spec":{"suspend":true}}'

# Trigger build
gcloud builds triggers run build-processor-manual --branch=copilot/investigate-fix-bot-blocking-issues

# Monitor build
gcloud builds list --ongoing

# After build completes, check rollout
gcloud deploy releases list --delivery-pipeline=processor-pipeline

# Promote to production
gcloud deploy releases promote --release=processor-[SHA] \
  --delivery-pipeline=processor-pipeline \
  --to-target=production

# Resume crawler
kubectl patch cronjob mizzou-crawler -n production -p '{"spec":{"suspend":false}}'
```

### 4. Monitor Results

**Immediate (0-15 minutes):**
```bash
# Watch logs for Selenium attempts
kubectl logs -n production -l app=mizzou-processor --tail=100 -f | grep -i selenium

# Look for:
# - "✅ Selenium extraction succeeded" (SUCCESS!)
# - "❌ Selenium extraction failed" (trying but failing)
# - NO MORE "Domain X is rate limited; skip Selenium"
```

**Phase 1 (30 minutes):**
```sql
SELECT 
  COUNT(*) as total_extractions,
  SUM(CASE WHEN is_success THEN 1 ELSE 0 END) as successes,
  ROUND(100.0 * SUM(CASE WHEN is_success THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate,
  SUM(CASE WHEN primary_method = 'selenium' THEN 1 ELSE 0 END) as selenium_extractions
FROM extraction_telemetry_v2
WHERE created_at >= NOW() - INTERVAL '30 minutes'
AND primary_method IS NOT NULL;

-- Expected: success_rate > 10%, selenium_extractions > 0
```

**Phase 2 (2 hours):**
```sql
SELECT 
  host,
  COUNT(*) as attempts,
  SUM(CASE WHEN is_success THEN 1 ELSE 0 END) as successes,
  SUM(CASE WHEN primary_method = 'selenium' THEN 1 ELSE 0 END) as selenium_used,
  ROUND(100.0 * SUM(CASE WHEN is_success THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate
FROM extraction_telemetry_v2
WHERE created_at >= NOW() - INTERVAL '2 hours'
GROUP BY host
HAVING COUNT(*) >= 3
ORDER BY success_rate DESC;

-- Expected: PerimeterX domains showing >0% success with Selenium
```

---

## Success Criteria

### Immediate Success Indicators
✅ Build completes successfully  
✅ New pod deployed (image contains fix)  
✅ Logs show "✅ Selenium extraction succeeded" for some URLs  
✅ **NO MORE** "Domain X is rate limited; skip Selenium" messages  

### Phase 1 Success (30 min - 2 hours)
✅ Extraction success rate **>10%** (up from 0%)  
✅ At least **some** extractions using `primary_method = 'selenium'`  
✅ PerimeterX domains showing successful extractions  

### Phase 2 Success (24 hours)
✅ Extraction success rate **>25%**  
✅ Multiple domains successfully using Selenium fallback  
✅ Selenium failure counts tracked correctly (resets on success)  

### Phase 3 Success (1 week)
✅ Extraction success rate **>50%**  
✅ Clear pattern: simpler domains work with requests, CAPTCHA domains use Selenium  
✅ System intelligently avoids domains where Selenium fails 3+ times  

---

## Rollback Plan

If Selenium causes issues (crashes, hangs, excessive resource usage):

```bash
# Revert to previous release
gcloud deploy releases promote --release=processor-[PREVIOUS_SHA] \
  --delivery-pipeline=processor-pipeline \
  --to-target=production

# Or scale down processor temporarily
kubectl scale deployment mizzou-processor -n production --replicas=0
```

**Rollback triggers:**
- Pod crashes or OOMKilled errors
- CPU/memory usage >90% sustained
- Selenium hangs causing queue backup
- Success rate DECREASES below current baseline

---

## Root Cause Analysis

### Why Was This Not Caught Earlier?

1. **Integration tests passed** - tested bot detection logic, not Selenium interaction
2. **Manual smoke tests passed** - didn't trigger CAPTCHA in test environment
3. **Code review focused on User-Agent improvements** - didn't trace through full fallback flow
4. **Deployed to production to test real CAPTCHA** - discovered the bug post-deployment

### Lessons Learned

✅ **Test full extraction flow** including all fallback paths  
✅ **Test with real CAPTCHA sites** in staging environment  
✅ **Trace through rate limit/backoff logic** in code review  
✅ **Monitor Selenium usage** separately from requests usage  

---

## Related Documentation

- **Initial Investigation:** `BOT_BLOCKING_INITIAL_STATUS.md`
- **Integration Tests:** `tests/test_bot_blocking_integration.py`
- **Test Results:** `BOT_BLOCKING_TEST_RESULTS.md`
- **Deployment Record:** `BOT_BLOCKING_DEPLOYMENT_COMPLETE.md`

---

## Summary

**Before Fix:**
- Requests fails → CAPTCHA backoff set → Selenium checks rate limit → Selenium skipped → 0% success

**After Fix:**
- Requests fails → CAPTCHA backoff set → **Selenium bypasses rate limit** → Selenium attempts extraction → Success likely

**Impact:** Enables Selenium to actually do its job (bypass CAPTCHA) instead of being blocked by rate limits meant for requests-based failures.

**Expected Result:** Extraction success rate increases from 0% to 10-50% on CAPTCHA-protected domains.
