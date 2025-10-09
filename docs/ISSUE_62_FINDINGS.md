# Issue #62 Investigation: Proxy and Anti-Bot Detection

## Executive Summary

Investigation into Issue #62 reveals that the system **IS designed correctly** with comprehensive anti-bot measures, but **lacks visibility** into whether these measures are working. This PR adds comprehensive diagnostic logging to answer the key question: *"Is the system working as designed?"*

## System Design Review

### ✅ Anti-Bot Measures Present

The system has the following anti-bot detection measures implemented:

1. **Origin Proxy Router** (`src/crawler/origin_proxy.py`)
   - ✅ Rewrites requests through `proxy.kiesow.net:23432`
   - ✅ Adds Basic authentication headers
   - ✅ Bypasses internal/metadata hosts
   - ✅ Configurable via `USE_ORIGIN_PROXY` env var

2. **Cloudscraper Integration** (`src/crawler/__init__.py`)
   - ✅ Uses cloudscraper to bypass Cloudflare protection
   - ✅ Falls back to requests.Session if unavailable
   - ✅ Applied to all HTTP sessions

3. **User-Agent Rotation**
   - ✅ Rotates User-Agents per domain
   - ✅ Pool of realistic browser User-Agents
   - ✅ Configurable rotation frequency
   - ✅ Domain-specific session management

4. **Rate Limiting & Backoff**
   - ✅ Exponential backoff for failed requests
   - ✅ CAPTCHA-aware backoff (15min - 2hr)
   - ✅ Domain-specific backoff tracking
   - ✅ Respects retry-after headers

5. **Session Management**
   - ✅ Domain-specific sessions with clean cookies
   - ✅ Request throttling with jitter
   - ✅ Dead URL caching
   - ✅ Thread-safe domain locking

### ❌ Problem: Lack of Visibility

The issue is **NOT** that the system lacks anti-bot measures, but that there was **no logging** to confirm they are working:

- ❌ No logging showing proxy is being used
- ❌ No logging showing authentication is present
- ❌ No logging showing cloudscraper is active
- ❌ No logging showing backoff timers
- ❌ No diagnostic tools to test configuration
- ❌ Limited visibility into actual errors

This meant we couldn't answer:
- Is the proxy being used for every request?
- Is authentication being added correctly?
- Is cloudscraper active or falling back to requests?
- Are backoff timers working as designed?
- What are the actual error responses from sites?

## Changes Made

### 1. Enhanced Proxy Logging (`src/crawler/origin_proxy.py`)

Added comprehensive logging to the proxy wrapper:

```python
# Before: Silent operation
def _wrapped_request(self, method, url, *args, **kwargs):
    use = os.getenv("USE_ORIGIN_PROXY", "").lower() in ("1", "true", "yes")
    if use and not _should_bypass(url):
        # ... proxy logic ...
        url = proxied
    return session._origin_original_request(method, url, *args, **kwargs)

# After: Full visibility
def _wrapped_request(self, method, url, *args, **kwargs):
    use = os.getenv("USE_ORIGIN_PROXY", "").lower() in ("1", "true", "yes")
    original_url = str(url)
    proxy_used = False
    
    if use:
        if _should_bypass(url):
            logger.debug(f"Origin proxy bypassed for {original_url[:80]}")
        else:
            # ... proxy logic ...
            proxy_used = True
            logger.info(
                f"🔀 Proxying {method} {domain} via {proxy_base} "
                f"(auth: {'yes' if has_auth else 'NO - MISSING CREDENTIALS'})"
            )
    
    try:
        response = session._origin_original_request(method, url, *args, **kwargs)
        if proxy_used:
            logger.info(f"✓ Proxy response {response.status_code} for {domain}")
        return response
    except Exception as e:
        if proxy_used:
            logger.error(f"✗ Proxy request failed for {domain}: {e}")
        raise
```

**Benefits:**
- ✅ Shows every proxied request
- ✅ Shows authentication status
- ✅ Shows proxy responses
- ✅ Shows proxy errors
- ✅ Shows bypass decisions

### 2. Enhanced ContentExtractor Logging (`src/crawler/__init__.py`)

Added logging at key points in the extraction flow:

```python
# Session creation
logger.info("🔧 Created new cloudscraper session (anti-Cloudflare enabled)")
logger.info("🔀 Origin proxy adapter installed (proxy: http://proxy.kiesow.net:23432)")

# Domain sessions
logger.info(
    f"🔧 Created cloudscraper session for {domain} "
    f"(proxy: {'enabled' if use_proxy else 'disabled'}, UA: {user_agent[:50]}...)"
)

# HTTP requests
logger.info(f"📡 Fetching {url[:80]}... via session for {domain}")
logger.info(f"📥 Received {http_status} for {domain} (content: {len(response.text)} bytes)")

# Bot detection
logger.warning(
    f"🚫 Bot detection ({response.status_code}) by {domain} "
    f"- response preview: {response.text[:200]}"
)

# Success
logger.info(f"✅ Successfully fetched {len(response.text)} bytes from {domain} (UA: {ua[:30]}...)")
```

**Benefits:**
- ✅ Shows cloudscraper vs requests usage
- ✅ Shows proxy enabled per domain
- ✅ Shows actual error responses
- ✅ Shows successful fetches
- ✅ Emoji indicators for easy scanning

### 3. Diagnostic Tool (`scripts/diagnose_proxy.py`)

Created comprehensive diagnostic script:

```python
def main():
    check_environment()          # Verify env vars
    test_proxy_connectivity()    # Test proxy is reachable
    test_cloudscraper()          # Verify cloudscraper works
    test_proxied_request()       # Test proxy routing
    test_real_site()             # Test real news sites
```

**Benefits:**
- ✅ Quick verification of configuration
- ✅ Tests proxy connectivity
- ✅ Tests authentication
- ✅ Tests cloudscraper
- ✅ Tests real sites
- ✅ Provides recommendations

### 4. Documentation (`docs/PROXY_DIAGNOSTICS.md`)

Complete guide for troubleshooting proxy issues:
- How to read the new log messages
- How to run diagnostics
- Common issues and solutions
- Configuration reference
- Testing procedures

## How to Verify System is Working

### Step 1: Deploy Changes

```bash
# Rebuild and deploy processor with new logging
kubectl rollout restart deployment/mizzou-processor -n production
```

### Step 2: Monitor Logs

```bash
# Watch processor logs
kubectl logs -n production -l app=mizzou-processor -f
```

### Step 3: Look for Key Indicators

**Proxy Usage:**
```
🔀 Proxying GET fultonsun.com via http://proxy.kiesow.net:23432 (auth: yes)
✓ Proxy response 200 for fultonsun.com
```
✅ **GOOD** - Proxy is being used with authentication

```
🔀 Proxying GET example.com via http://proxy.kiesow.net:23432 (auth: NO - MISSING CREDENTIALS)
```
⚠️ **WARNING** - Proxy used but credentials missing

**Cloudscraper:**
```
🔧 Created new cloudscraper session (anti-Cloudflare enabled)
```
✅ **GOOD** - Cloudscraper is active

```
🔧 Created new requests session (cloudscraper NOT available)
```
⚠️ **WARNING** - Falling back to basic requests

**Bot Detection:**
```
🚫 Bot detection (403) by fultonsun.com - response preview: <html>...
CAPTCHA backoff for fultonsun.com: 900s (attempt 1)
```
✅ **EXPECTED** - System detecting and backing off

**Success:**
```
✅ Successfully fetched 45678 bytes from columbiatribune.com (UA: Mozilla/5.0...)
```
✅ **GOOD** - Extraction working

### Step 4: Run Diagnostics

```bash
# From within processor pod or with credentials
export USE_ORIGIN_PROXY=1
export ORIGIN_PROXY_URL=http://proxy.kiesow.net:23432
export PROXY_USERNAME=<username>
export PROXY_PASSWORD=<password>

python scripts/diagnose_proxy.py
```

Look for:
- ✅ All environment variables present
- ✅ Proxy is reachable
- ✅ Cloudscraper is installed
- ✅ Proxied requests succeed
- ✅ Real sites accessible

## Expected Findings

Based on Issue #62 description, we expect to see:

### What Should Work
1. ✅ Proxy is being used for all requests
2. ✅ Authentication is present
3. ✅ Cloudscraper is active
4. ✅ Backoff timers are working
5. ✅ User-Agents are rotating

### What Might Be Failing
1. ⚠️ Proxy returning 400 errors for some URLs
2. ⚠️ Cloudflare CAPTCHA still blocking some domains
3. ⚠️ Some domains have very aggressive rate limiting
4. ⚠️ 124 articles stuck in retry loop

### Root Causes
Based on logs, the likely issues are:

**Issue 1: Proxy 400 Errors**
- Proxy may not handle certain URL encodings
- May be proxy server configuration issue
- Need to check proxy logs

**Issue 2: Cloudflare Protection**
- Even with cloudscraper, some Cloudflare configs are very aggressive
- May need residential proxy + CAPTCHA solver
- Or may need to skip these domains

**Issue 3: Rate Limiting**
- Domains like ozarksfirst.com have strict limits
- Backoff is working as designed
- May need longer backoffs or skip after N attempts

**Issue 4: Queue Clogging**
- 124 articles stuck = need retry limit
- Should mark as `extraction_failed` after N attempts
- Prevents queue from clogging

## Recommendations

### Immediate (Today)

1. **Deploy these changes** to get visibility
2. **Monitor logs** for 1-2 hours
3. **Document findings** - What's working, what's not
4. **Run diagnostic script** to verify configuration

### Short-Term (This Week)

Based on log findings:

**If proxy is NOT being used:**
- Check `USE_ORIGIN_PROXY` environment variable
- Verify credentials in secret
- Check deployment has env vars

**If getting 400 errors:**
- Check proxy server logs
- Test with diagnostic script
- May need proxy server configuration changes

**If Cloudflare blocking:**
- Verify cloudscraper is active (should be)
- Consider residential proxy service
- Consider CAPTCHA solving service
- Or skip these domains

**If rate limiting:**
- Increase backoff timers
- Reduce discovery frequency
- Implement retry limits

### Medium-Term (Next Sprint)

1. **Implement retry limits** (Option 1 from Issue #62)
   - Add `retry_count` column
   - Mark `extraction_failed` after 5 attempts
   - Unblock queue

2. **Improve error handling**
   - Better differentiation of error types
   - Automatic domain health tracking
   - Prioritize high-success domains

3. **Consider paid services** (if ROI justifies)
   - Residential proxies (BrightData, Oxylabs)
   - CAPTCHA solving (2Captcha, Anti-Captcha)
   - Cost vs benefit analysis

## Success Criteria

This investigation is successful when we can answer:

1. ✅ Is the proxy being used? → **Check logs for "Proxying" messages**
2. ✅ Is authentication present? → **Check logs show "auth: yes"**
3. ✅ Is cloudscraper active? → **Check logs show "cloudscraper session"**
4. ✅ Are backoffs working? → **Check logs show backoff timers**
5. ✅ What are actual errors? → **Check logs show response previews**

With this visibility, we can then:
- Identify specific configuration issues
- Determine if proxy server needs changes
- Decide which domains to skip
- Implement appropriate solutions

## Files Changed

1. `src/crawler/origin_proxy.py` - Enhanced proxy logging
2. `src/crawler/__init__.py` - Enhanced extractor logging
3. `scripts/diagnose_proxy.py` - New diagnostic tool
4. `docs/PROXY_DIAGNOSTICS.md` - Complete troubleshooting guide
5. `docs/ISSUE_62_FINDINGS.md` - This document

## Next Actions

1. **Deploy** - Merge PR and deploy to production
2. **Monitor** - Watch logs for 1-2 hours
3. **Document** - Update Issue #62 with findings
4. **Decide** - Based on findings, implement appropriate fixes
5. **Track** - Monitor success rate improvements

## Conclusion

The system **is designed correctly** with comprehensive anti-bot measures. The problem was **lack of visibility**. These changes provide the logging and diagnostics needed to:

1. Verify the system is working as designed
2. Identify specific configuration issues
3. Determine appropriate fixes
4. Monitor improvements

Once deployed, we'll have clear visibility into:
- Whether proxy is being used correctly
- Whether authentication is present
- Whether cloudscraper is active
- Whether backoffs are working
- What the actual errors are

This will allow us to make **data-driven decisions** about next steps.
