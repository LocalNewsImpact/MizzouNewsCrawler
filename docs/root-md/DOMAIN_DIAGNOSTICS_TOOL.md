# Domain Extraction Diagnostics Tool

## Overview

You now have a **single-command domain testing tool** that tests extraction on specific domains in production and gives you **clear diagnostics about what's failing and how to fix it**.

## Usage

```bash
# Test a domain with default settings (3 URLs from that domain)
python -m src.cli.cli_modular test-domain --domain example.com

# Test with more URLs
python -m src.cli.cli_modular test-domain --domain example.com --limit 10

# Show detailed extraction logs
python -m src.cli.cli_modular test-domain --domain example.com --verbose

# Save results to JSON for later analysis
python -m src.cli.cli_modular test-domain --domain example.com --output results.json
```

## Example Output

```
================================================================================
DOMAIN EXTRACTION DIAGNOSTICS: example.com
================================================================================

📍 Normalized domain: example.com
✓ Found 3 articles to test

[1/3] Testing: https://example.com/article-1
--------------------------------------------------------------------------------
✅ SUCCESS - Extracted 2345 chars
   ✓ Missing fields: published_date

   Extracted fields:
   ✓ title              Article Title Goes Here
   ✓ author             John Doe
   ✗ published_date     (empty)
   ✓ content            Article content extracted successfully...

[2/3] Testing: https://example.com/article-2
--------------------------------------------------------------------------------
❌ FAILURE - Could not extract content
   • extraction: HTTP 403 Forbidden (access denied)

   Extracted fields:
   ✗ title              (empty)
   ✗ author             (empty)
   ✗ published_date     (empty)
   ✗ content            (empty)

[3/3] Testing: https://example.com/article-3
--------------------------------------------------------------------------------
⚠️ PARTIAL - Extracted 892 chars
   Missing: author, published_date

   Extracted fields:
   ✓ title              Another Article
   ✗ author             (empty)
   ✗ published_date     (empty)
   ✓ content            Partial content extracted...

================================================================================
SUMMARY
================================================================================

Results: 1 success, 1 partial, 1 failure

Error types encountered:
  • HTTP_403_FORBIDDEN: 1

================================================================================
RECOMMENDATIONS
================================================================================

✗ example.com returned HTTP 403 Forbidden (access denied)
→ Try rotating User-Agent: UA_ROTATE_BASE > 1
→ Add delay between requests: INTER_REQUEST_MIN=5 INTER_REQUEST_MAX=15
→ Try Selenium with headful mode for JS-rendered content
→ Check if bot detection (PerimeterX, Akamai) is active

================================================================================
```

## What It Does

1. **Finds articles**: Queries the database for articles from the domain you specify
2. **Extracts content**: Runs the full extraction pipeline on each URL
3. **Shows results**: Displays which fields were extracted and which are missing
4. **Categorizes errors**: Identifies the type of failure (Cloudflare, proxy, timeout, etc.)
5. **Recommends fixes**: Suggests specific actions based on the error type

## Error Categories

The tool automatically identifies and categorizes failures:

| Category | What It Means | Example Cause |
|----------|--------------|---------------|
| `CLOUDFLARE_PROTECTION` | Site is protected by Cloudflare | CDN protection active |
| `SUBSCRIPTION_WALL` | Site has paywall/subscription | News sites with paywalls |
| `PROXY_CHALLENGE` | Proxy access detected & blocked | Squid proxy detected as suspicious |
| `HTTP_403_FORBIDDEN` | Server denied access | Bot detection (PerimeterX, Akamai) |
| `HTTP_404_NOT_FOUND` | URL doesn't exist | Dead or changed URL structure |
| `TIMEOUT` | Request took too long | Network latency or slow proxy |
| `CHROME_DRIVER_ERROR` | Chrome/Selenium issue | Chrome crash, display error |
| `CONNECTION_ERROR` | Cannot reach server | Network issue or geo-blocking |

## Recommendations

For each error type, the tool provides actionable recommendations. Examples:

### Cloudflare Protection
```
→ Ensure cloudscraper session is enabled (already enabled by default)
→ Try adding Domain to CLOUDFLARE_ESCALATION_DOMAINS in config
→ Increase CLOUDFLARE_MAX_RETRIES if intermittent
```

### Proxy Challenge
```
→ Verify Squid proxy is reachable: curl --proxy http://t9880447.eero.online:3128 http://example.com/
→ Check proxy rotation settings (may need residential IP pool rotation)
→ Enable Squid-to-residential retry: PROXY_ROTATION_ENABLED=true
→ If persistent, add domain to PROXY_BYPASS_DOMAINS (use direct HTTP)
```

### HTTP 403 Forbidden
```
→ Try rotating User-Agent: UA_ROTATE_BASE > 1
→ Add delay between requests: INTER_REQUEST_MIN=5 INTER_REQUEST_MAX=15
→ Try Selenium with headful mode for JS-rendered content
→ Check if bot detection (PerimeterX, Akamai) is active
```

## Testing in Production Pod

You can also run this directly in the production extraction pod:

```bash
# SSH into pod
kubectl exec -it -n production deployment/mizzou-crawler -- /bin/bash

# Run diagnostics
python -m src.cli.cli_modular test-domain --domain example.com --verbose

# Save results for download
python -m src.cli.cli_modular test-domain --domain example.com --output /tmp/results.json
```

## Common Workflows

### I need to know why a domain isn't extracting
```bash
python -m src.cli.cli_modular test-domain --domain problematic-domain.com --verbose
# Look at the error category in RECOMMENDATIONS section
```

### I want to test before fixing config
```bash
python -m src.cli.cli_modular test-domain --domain example.com --limit 10 --output before.json
# Make config changes
python -m src.cli.cli_modular test-domain --domain example.com --limit 10 --output after.json
# Compare results
```

### I need diagnostics for a bug report
```bash
python -m src.cli.cli_modular test-domain --domain example.com --verbose --output diag.json
# Attach diag.json and console output to bug report
```

## What's Different from Before

**Before**: Unclear diagnostics, had to run multiple commands, hard to understand what failed and why

**Now**:
- ✅ Single command tests a specific domain
- ✅ Clear PASS/FAIL status for each URL
- ✅ Shows exactly which fields extracted and which didn't
- ✅ Automatically categorizes error types
- ✅ Provides specific, actionable recommendations for each error
- ✅ Saves results to JSON for analysis or bug reports
