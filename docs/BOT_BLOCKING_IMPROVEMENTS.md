# Bot Blocking Improvements - Issue #64

## Overview

This document describes the improvements made to address the critical bot blocking issues identified in [Issue #64](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/64). The improvements focus on making the crawler's requests appear more like legitimate browser traffic to reduce detection and blocking by bot protection systems.

## Problem Statement

The crawler was experiencing **100% bot detection blocking** across multiple news domains, with all extraction attempts failing with 403 Forbidden responses or CAPTCHA challenges. Key issues identified:

- Outdated User-Agent strings easily identified as automated
- Missing or unrealistic HTTP headers
- Lack of Referer headers (natural browser navigation includes these)
- Generic bot detection not being specifically identified
- All 403/503 errors treated the same regardless of cause

## Implemented Solutions

### 1. User-Agent Pool Updates

**Problem**: Old User-Agent strings (Chrome 119-120) were easily flagged as outdated or automated.

**Solution**: Updated the User-Agent pool with the latest browser versions as of October 2025:

- **Chrome**: Versions 127, 128, 129
- **Firefox**: Versions 130, 131
- **Safari**: Versions 17.6, 18.0
- **Edge**: Version 129
- **Platforms**: Windows 10, macOS 10.15, Linux (X11)

**Total**: 13 different User-Agent combinations providing good variety while staying current.

```python
# Example User-Agents now in use:
"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
"Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:130.0) Gecko/20100101 Firefox/130.0"
"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
```

### 2. Realistic Accept Headers

**Problem**: Generic Accept headers didn't match real browsers.

**Solution**: Added modern Accept header variations that include current image formats:

```python
accept_header_pool = [
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
]
```

**Key improvements**:
- Support for modern image formats: AVIF, WebP, APNG
- Proper quality values (q=0.9, q=0.8, q=0.7)
- Signed exchange support (v=b3)

### 3. Enhanced Header Variations

**Accept-Language**: Expanded from 5 to 7 variations, including multi-language preferences:
```python
"en-US,en;q=0.9"
"en-US,en;q=0.9,es;q=0.8"
"en-US,en;q=0.9,fr;q=0.8,de;q=0.7"
```

**Accept-Encoding**: Prioritizes modern compression with Zstandard:
```python
"gzip, deflate, br, zstd"  # Most modern
"gzip, deflate, br"        # Standard
"gzip, deflate"            # Legacy
```

### 4. Referer Header Generation

**Problem**: Requests without Referer headers don't match natural browsing patterns.

**Solution**: Implemented dynamic Referer generation with multiple strategies:

- **40% - Homepage**: `https://example.com/`
- **30% - Same Domain**: `https://example.com/news`, `https://example.com/articles`
- **20% - Google Search**: `https://www.google.com/`
- **10% - No Referer**: (Some browsers/privacy tools omit this)

This makes each request look like it came from realistic navigation.

### 5. Sec-Fetch-* Headers

Added proper Sec-Fetch headers that modern browsers send:

```python
"Sec-Fetch-Dest": "document"
"Sec-Fetch-Mode": "navigate"
"Sec-Fetch-Site": "none"
"Sec-Fetch-User": "?1"
```

### 6. Optional DNT Header

**Problem**: All requests had "DNT: 1" header, but not all browsers send this.

**Solution**: Made DNT header optional with 70% probability, better matching real-world traffic distribution.

### 7. Bot Protection Detection

**Problem**: All 403/503 errors were treated the same, even though some were bot protection and others were server issues.

**Solution**: Implemented `_detect_bot_protection_in_response()` that identifies:

1. **Cloudflare Protection**:
   - "Checking your browser"
   - "Cloudflare Ray ID"
   - "Just a moment..."
   - "Under attack mode"

2. **Generic Bot Protection**:
   - "Access denied"
   - "Blocked by"
   - "Security check"
   - "Are you a robot"
   - CAPTCHA/reCAPTCHA indicators

3. **Suspicious Responses**:
   - Very short responses (<500 bytes) with 403/503 status

### 8. Differentiated Backoff Strategies

**Problem**: All errors triggered the same exponential backoff.

**Solution**: Implemented different backoff strategies based on error type:

| Error Type | Backoff Strategy | Base Delay | Max Delay |
|------------|------------------|------------|-----------|
| Cloudflare/CAPTCHA | CAPTCHA backoff | 10 minutes | 90 minutes |
| Bot Protection | CAPTCHA backoff | 10 minutes | 90 minutes |
| Rate Limit (429) | Standard backoff | 1 minute | 60 minutes |
| Server Error (503) | Standard backoff | 1 minute | 60 minutes |

This ensures confirmed bot protection triggers longer delays while temporary server issues get shorter delays.

### 9. Detection in 200 Responses

**Problem**: Some bot protection (especially Cloudflare) returns 200 status with a challenge page.

**Solution**: Added bot protection detection even for successful status codes, catching challenge pages before attempting to parse them.

## NewsCrawler Default User-Agent

Changed the default User-Agent from bot-identifying to realistic:

**Before**:
```python
"Mozilla/5.0 (compatible; MizzouCrawler/1.0)"  # Easily blocked
```

**After**:
```python
"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
```

## Testing

Comprehensive test suite added in `tests/test_bot_blocking_improvements.py`:

- **User Agent Tests**: Verify pool size, recent versions, multiple browsers/platforms
- **Header Tests**: Validate Accept header variations and modern format support
- **Referer Tests**: Check generation logic, variation, and same-domain patterns
- **Bot Protection Tests**: Validate detection of Cloudflare, CAPTCHA, generic protection
- **Session Management Tests**: Verify rotation statistics are available

All tests pass successfully.

## Expected Impact

These improvements should significantly reduce bot detection rates by:

1. **Appearing More Current**: Latest browser versions reduce fingerprinting
2. **More Natural Headers**: Complete and varied headers match real browsers
3. **Navigation Patterns**: Referer headers simulate realistic browsing
4. **Better Response**: Longer backoffs for confirmed bot protection reduce repeated blocks
5. **Intelligent Detection**: Differentiating protection types allows appropriate responses

## Configuration

The improvements use existing environment variables plus sensible defaults:

| Variable | Default | Purpose |
|----------|---------|---------|
| `UA_ROTATE_BASE` | 9 | Requests before rotating User-Agent |
| `UA_ROTATE_JITTER` | 0.25 | Randomness in rotation timing |
| `INTER_REQUEST_MIN` | 1.5s | Minimum delay between requests |
| `INTER_REQUEST_MAX` | 3.5s | Maximum delay between requests |
| `CAPTCHA_BACKOFF_BASE` | 600s | Base delay for CAPTCHA (10 min) |
| `CAPTCHA_BACKOFF_MAX` | 5400s | Max delay for CAPTCHA (90 min) |

## Monitoring

Track these metrics to assess improvement effectiveness:

1. **Extraction Success Rate**: Should increase from 0% baseline
2. **403/503 Error Rate**: Should decrease
3. **Bot Protection Detection**: Track Cloudflare vs generic vs none
4. **Backoff Duration**: Average and max backoff times by domain
5. **User Agent Distribution**: Ensure rotation is working

Query example:
```sql
SELECT 
  DATE(created_at) as date,
  COUNT(*) as total_attempts,
  SUM(CASE WHEN is_success THEN 1 ELSE 0 END) as successful,
  ROUND(100.0 * SUM(CASE WHEN is_success THEN 1 ELSE 0 END) / COUNT(*), 1) as success_rate,
  SUM(CASE WHEN http_status_code = 403 THEN 1 ELSE 0 END) as blocked_403
FROM extraction_telemetry_v2
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY DATE(created_at)
ORDER BY date DESC;
```

## Next Steps (Not Implemented Yet)

The following were identified in Issue #64 but not yet implemented:

### Short-term Improvements
1. **Selenium Priority**: Use Selenium first for known-blocked domains
2. **Slower Request Rate**: Configurable per-domain delays (10-30s for problematic sites)
3. **Direct vs Proxy Testing**: A/B test proxy effectiveness

### Medium-term Improvements
1. **Undetected ChromeDriver**: Switch to more advanced anti-detection driver
2. **Request Pattern Randomization**: Vary article order and batch timing
3. **Domain-Specific Strategies**: Track per-domain success and adjust approach

### Long-term Improvements
1. **Distributed Crawling**: Multiple crawler pods with different IPs
2. **Cloud NAT Rotation**: Multiple external IPs for better distribution
3. **RSS/API Alternatives**: Use official feeds where available
4. **Publisher Partnerships**: Legitimate access arrangements

## Related Issues

- [Issue #64](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/64) - Critical bot blocking investigation
- Proxy Telemetry Deployment (commit 72e394c) - Monitoring infrastructure

## Files Changed

- `src/crawler/__init__.py` - Core improvements
- `tests/test_bot_blocking_improvements.py` - New test suite
- `docs/BOT_BLOCKING_IMPROVEMENTS.md` - This documentation

## Summary

These improvements represent a comprehensive update to the crawler's anti-detection capabilities, focusing on making automated requests indistinguishable from legitimate browser traffic. The combination of modern User-Agents, realistic headers, natural navigation patterns (Referer), and intelligent bot protection detection should significantly reduce blocking rates while maintaining respectful crawling practices through appropriate backoff strategies.
