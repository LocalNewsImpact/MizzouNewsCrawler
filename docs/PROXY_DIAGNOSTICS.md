# Proxy and Anti-Bot Detection Diagnostics

This document explains how to diagnose proxy and anti-bot detection issues using the enhanced logging and diagnostic tools added to address Issue #62.

## Overview

The system uses several anti-bot detection measures:
1. **Origin Proxy** (`proxy.kiesow.net:23432`) - Routes requests through a proxy server
2. **Cloudscraper** - Bypasses Cloudflare protection
3. **User-Agent Rotation** - Rotates browser User-Agents per domain
4. **Rate Limiting & Backoff** - Exponential backoff for failed requests
5. **Session Management** - Domain-specific sessions with clean cookies

## Enhanced Logging

The system now includes comprehensive logging with emoji indicators for easy scanning:

### Session Creation
```
🔧 Created new cloudscraper session (anti-Cloudflare enabled)
🔀 Origin proxy adapter installed (proxy: http://proxy.kiesow.net:23432)
```

### Domain Sessions
```
🔧 Created cloudscraper session for example.com (proxy: enabled, UA: Mozilla/5.0...)
```

### Proxy Usage
```
🔀 Proxying GET example.com via http://proxy.kiesow.net:23432 (auth: yes)
✓ Proxy response 200 for example.com
✗ Proxy request failed for example.com: ConnectionError: ...
```

### HTTP Requests
```
📡 Fetching https://example.com/article... via session for example.com
📥 Received 200 for example.com (content: 45678 bytes)
✅ Successfully fetched 45678 bytes from example.com (UA: Mozilla/5.0...)
```

### Bot Detection
```
🚫 Bot detection (403) by example.com - response preview: <html><body>Access Denied...
CAPTCHA backoff for example.com: 900s (attempt 1)
```

## Diagnostic Script

Run the diagnostic script to test proxy configuration and connectivity:

```bash
# Set up environment (if not already configured)
export USE_ORIGIN_PROXY=1
export ORIGIN_PROXY_URL=http://proxy.kiesow.net:23432
export PROXY_USERNAME=your_username
export PROXY_PASSWORD=your_password

# Run diagnostics
python scripts/diagnose_proxy.py
```

The script will:
1. ✓ Check environment variables
2. ✓ Test proxy server connectivity
3. ✓ Test cloudscraper availability
4. ✓ Test proxied requests to test sites
5. ✓ Test fetching real news sites
6. ✓ Provide recommendations

### Expected Output

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                    PROXY DIAGNOSTIC TOOL                                     ║
╚══════════════════════════════════════════════════════════════════════════════╝

================================================================================
ENVIRONMENT VARIABLES
================================================================================
  ✓ USE_ORIGIN_PROXY=1
  ✓ ORIGIN_PROXY_URL=http://proxy.kiesow.net:23432
  ✓ PROXY_USERNAME=your_username
  ✓ PROXY_PASSWORD=***********

================================================================================
PROXY CONNECTIVITY TEST
================================================================================
Testing connectivity to: http://proxy.kiesow.net:23432
  ✓ Proxy is reachable (status: 200)

================================================================================
CLOUDSCRAPER TEST
================================================================================
  ✓ cloudscraper is installed
  ✓ cloudscraper session created successfully
  ✓ Test request succeeded (status: 200)

================================================================================
PROXIED REQUEST TEST
================================================================================
USE_ORIGIN_PROXY: True

Testing: http://httpbin.org/ip
  ✓ Status: 200
  Content length: 35 bytes

================================================================================
REAL SITE TEST
================================================================================
Testing: https://www.example.com/
  Proxy enabled: True
  ✓ Status: 200
  Content length: 1256 bytes
```

## Monitoring Processor Logs

When the processor is running, monitor logs to verify the system is working:

### 1. Check Proxy is Being Used

Look for proxy logging messages:
```bash
kubectl logs -n production -l app=mizzou-processor --tail=100 | grep "Proxying"
```

Expected output:
```
🔀 Proxying GET fultonsun.com via http://proxy.kiesow.net:23432 (auth: yes)
🔀 Proxying GET newstribune.com via http://proxy.kiesow.net:23432 (auth: yes)
```

**⚠️ Warning Signs:**
- `auth: NO - MISSING CREDENTIALS` - Credentials not configured
- No "Proxying" messages - Proxy not being used at all
- Messages show `bypassed` - URLs are being bypassed incorrectly

### 2. Check Authentication

Verify credentials are present:
```bash
kubectl get secret -n production origin-proxy-credentials -o jsonpath='{.data}' | jq
```

### 3. Check Cloudscraper

Look for cloudscraper usage:
```bash
kubectl logs -n production -l app=mizzou-processor --tail=100 | grep "cloudscraper"
```

Expected output:
```
🔧 Created new cloudscraper session (anti-Cloudflare enabled)
🔧 Created cloudscraper session for fultonsun.com (proxy: enabled, ...)
```

**⚠️ Warning Signs:**
- `cloudscraper NOT available` - Package not installed
- `Created new requests session` - Falling back to basic requests

### 4. Check Rate Limiting and Backoff

Look for backoff messages:
```bash
kubectl logs -n production -l app=mizzou-processor --tail=100 | grep "backoff\|rate limit"
```

Expected output:
```
🚫 Bot detection (403) by fultonsun.com - response preview: ...
CAPTCHA backoff for fultonsun.com: 900s (attempt 1)
Rate limited by ozarksfirst.com, backing off for 60s (attempt 1)
```

### 5. Check Success Rate

Count successful vs failed fetches:
```bash
# Successful fetches
kubectl logs -n production -l app=mizzou-processor --tail=500 | grep -c "Successfully fetched"

# Failed fetches
kubectl logs -n production -l app=mizzou-processor --tail=500 | grep -c "Bot detection"
```

## Common Issues and Solutions

### Issue 1: Proxy Not Being Used

**Symptoms:**
- No "Proxying" messages in logs
- Direct connection errors

**Solutions:**
1. Check `USE_ORIGIN_PROXY` environment variable is set to `1` or `true`
2. Verify proxy URL is configured: `ORIGIN_PROXY_URL`
3. Check deployment YAML has environment variables set

### Issue 2: 400 BAD REQUEST from Proxy

**Symptoms:**
```
✗ Proxy request failed for example.com: 400 Client Error: BAD REQUEST
```

**Possible Causes:**
1. Malformed URL encoding
2. Proxy authentication issue
3. Proxy server configuration issue
4. URL contains characters proxy can't handle

**Solutions:**
1. Check proxy logs for more details
2. Verify authentication credentials are correct
3. Test with diagnostic script
4. Check if specific URLs are causing issues

### Issue 3: Missing Authentication

**Symptoms:**
```
🔀 Proxying GET example.com via http://proxy.kiesow.net:23432 (auth: NO - MISSING CREDENTIALS)
```

**Solutions:**
1. Set `PROXY_USERNAME` and `PROXY_PASSWORD` environment variables
2. Check Kubernetes secret `origin-proxy-credentials` exists
3. Verify secret is mounted in deployment

### Issue 4: Cloudflare CAPTCHA

**Symptoms:**
```
🚫 Bot detection (403) by fultonsun.com - response preview: <html>...Cloudflare...
CAPTCHA backoff for fultonsun.com: 900s (attempt 1)
```

**Solutions:**
1. Verify cloudscraper is installed and being used
2. Increase backoff timers: `CAPTCHA_BACKOFF_BASE`, `CAPTCHA_BACKOFF_MAX`
3. Consider residential proxy service
4. Check if User-Agent rotation is working
5. May need CAPTCHA solving service for persistent blocks

### Issue 5: Rate Limiting (403)

**Symptoms:**
```
🚫 Bot detection (403) by ozarksfirst.com
Rate limited, backing off for 60s (attempt 1)
```

**Solutions:**
1. Backoff will automatically increase exponentially
2. Verify inter-request delays: `INTER_REQUEST_MIN`, `INTER_REQUEST_MAX`
3. Check if domain has very strict rate limits
4. May need to reduce discovery frequency for this source

## Configuration Reference

Environment variables that control proxy and anti-bot behavior:

### Proxy Configuration
- `USE_ORIGIN_PROXY` - Enable/disable proxy (1, true, yes to enable)
- `ORIGIN_PROXY_URL` - Proxy server URL (e.g., http://proxy.kiesow.net:23432)
- `PROXY_USERNAME` - Proxy authentication username
- `PROXY_PASSWORD` - Proxy authentication password
- `NO_PROXY` - Comma-separated list of hosts to bypass

### Rate Limiting
- `INTER_REQUEST_MIN` - Minimum delay between requests (default: 1.5s)
- `INTER_REQUEST_MAX` - Maximum delay between requests (default: 3.5s)
- `CAPTCHA_BACKOFF_BASE` - Base backoff for CAPTCHA (default: 600s / 10min)
- `CAPTCHA_BACKOFF_MAX` - Max backoff for CAPTCHA (default: 5400s / 90min)

### User-Agent Rotation
- `UA_ROTATE_BASE` - Requests before rotating UA (default: 9)
- `UA_ROTATE_JITTER` - Jitter factor for rotation (default: 0.25)

### Session Management
- `REQUEST_TIMEOUT` - HTTP request timeout (default: 20s)
- `DEAD_URL_TTL_SECONDS` - Cache dead URLs for this long (default: 604800s / 7 days)

## Testing Changes

After making configuration changes:

1. **Restart processor:**
   ```bash
   kubectl rollout restart deployment/mizzou-processor -n production
   ```

2. **Watch logs:**
   ```bash
   kubectl logs -n production -l app=mizzou-processor -f
   ```

3. **Look for new log messages:**
   - Check proxy is being used
   - Verify authentication is present
   - Monitor success rate
   - Check for bot detection

4. **Monitor metrics:**
   - Check extraction success rate in telemetry
   - Monitor backoff timers
   - Track which domains are failing

## Recommendations

Based on the logging and diagnostics:

1. **Verify proxy is working:**
   - Run diagnostic script
   - Check for "Proxying" messages in logs
   - Verify authentication is present

2. **Monitor backoff behavior:**
   - Check backoff timers are increasing
   - Verify domains respect backoff periods
   - Adjust timers if needed

3. **Track domain success rates:**
   - Identify problematic domains
   - Consider pausing consistently failing sources
   - Focus on high-success domains

4. **Consider upgrades:**
   - Residential proxy service (expensive but effective)
   - CAPTCHA solving service (for persistent blocks)
   - More aggressive User-Agent rotation

5. **Implement retry limits:**
   - Add `retry_count` column to track failures
   - Mark as `extraction_failed` after N attempts
   - Prevents queue from clogging with unfetchable articles

## Related Files

- `src/crawler/origin_proxy.py` - Proxy wrapper implementation
- `src/crawler/__init__.py` - ContentExtractor with cloudscraper
- `scripts/diagnose_proxy.py` - Diagnostic tool
- `k8s/processor-deployment.yaml` - Deployment configuration
- `k8s/origin-sitecustomize-configmap.yaml` - Sitecustomize integration

## Related Issues

- Issue #62: Extraction degraded due to anti-bot protection
- Issue #57: Processor errors (resolved)
- Issue #56: Pipeline visibility improvements
