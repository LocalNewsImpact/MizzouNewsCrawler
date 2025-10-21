# Decodo ISP Proxy Integration

**Date:** October 10, 2025  
**Status:** ✅ Tested and Ready  
**Proxy Type:** ISP proxy with built-in US credentials

---

## Summary

Added Decodo ISP proxy as the 8th provider option in the multi-proxy system. This proxy has **built-in credentials** and is ready to test immediately without any additional configuration.

## Key Details

**Proxy Information:**
- **Provider:** Decodo (isp.decodo.com)
- **Port:** 10000
- **Protocol:** HTTP (not HTTPS)
- **Location:** United States (Astound Broadband ISP)
- **Credentials:** Pre-configured in code
- **IP Address:** 216.132.139.41 (rotating)

**Test Results:**
- ✅ Basic connectivity: PASSED
- ✅ News website access (kansascity.com): PASSED (200 OK, 0.70s)
- ✅ Content extraction (columbiamissourian.com): PASSED (200 OK, 0.31s)
- ⚠️ Bot blocking indicators: DETECTED (captcha/blocked keywords in content)

**Note:** The bot blocking warning may be a false positive (keywords in JavaScript code), but should be verified with actual extraction tests.

---

## How to Use

### Quick Test (Recommended First Step)

```bash
# Switch to Decodo proxy
kubectl set env deployment/mizzou-processor -n production PROXY_PROVIDER=decodo

# Wait for rollout
kubectl rollout status deployment/mizzou-processor -n production

# Monitor extraction for 30 minutes
kubectl logs -n production -l app=mizzou-processor -f | grep -E "(extraction|Extracted|Success rate)"
```

### Check Results

After 30 minutes, check extraction success rate:

```bash
kubectl exec -n production deployment/mizzou-processor -- python3 -c "
from src.models.database import DatabaseManager
from sqlalchemy import text
db = DatabaseManager()
session = db.get_session().__enter__()

# Check recent extractions
recent = session.execute(text('''
    SELECT COUNT(*) FROM articles 
    WHERE status = 'extracted' 
    AND created_at >= NOW() - INTERVAL '30 minutes'
''')).scalar()

# Check total in queue
queue = session.execute(text('''
    SELECT COUNT(*) FROM articles WHERE status = 'extraction_pending'
''')).scalar()

print(f'Extracted (last 30 min): {recent}')
print(f'Queue remaining: {queue}')
"
```

### Switch Back

```bash
# Return to origin proxy
kubectl set env deployment/mizzou-processor -n production PROXY_PROVIDER=origin
```

---

## Configuration

The Decodo proxy has **default credentials built-in**, so it works immediately with just:

```bash
PROXY_PROVIDER=decodo
```

### Optional Overrides

If you need to customize:

```bash
DECODO_USERNAME=user-sp8z2fzi1e-country-us  # Default provided
DECODO_PASSWORD=qg_hJ7reok8e5F7BHg          # Default provided
DECODO_HOST=isp.decodo.com                   # Default provided
DECODO_PORT=10000                            # Default provided
DECODO_COUNTRY=us                            # Target country
```

---

## Files Modified

1. **src/crawler/proxy_config.py**
   - Added `ProxyProvider.DECODO` enum
   - Added Decodo configuration loader with defaults
   - Uses HTTP protocol (not HTTPS)

2. **docs/PROXY_CONFIGURATION.md**
   - Added Section 8: Decodo ISP Proxy
   - Documented built-in credentials
   - Usage examples

3. **MULTI_PROXY_IMPLEMENTATION.md**
   - Added Decodo to provider table
   - Listed as second option (after origin, before direct)

4. **test_decodo_proxy.py** (NEW)
   - Standalone test script
   - Tests 3 scenarios: IP check, news site access, bot blocking detection
   - Run with: `python3 test_decodo_proxy.py`

---

## Why Decodo?

### Advantages
- ✅ **No signup required** - Credentials built into code
- ✅ **ISP-level proxy** - Real residential ISP (Astound Broadband)
- ✅ **US-based** - Matches target news site geography
- ✅ **Fast** - 0.3-0.7s response times
- ✅ **Rotating IPs** - Different IP each request
- ✅ **Ready to test** - Just set `PROXY_PROVIDER=decodo`

### Comparison to Current (Origin Proxy)
| Feature | Origin (proxy.kiesow.net) | Decodo (isp.decodo.com) |
|---------|---------------------------|-------------------------|
| Type | Unknown/datacenter | ISP/residential |
| Location | Unknown | US (Kansas/Missouri region) |
| IP Rotation | Unknown | Yes (rotating) |
| Cost | ~$2-6/month | (Need to verify) |
| Setup | Requires credentials | Built-in credentials |
| Bot Detection Risk | High (may be blocked) | Lower (residential ISP) |

---

## Testing Strategy

### Phase 1: Compare with Origin (RECOMMENDED)

Run both proxies side-by-side for 1 hour:

1. **Current state:** Origin proxy running, check success rate
2. **Switch to Decodo:** Set `PROXY_PROVIDER=decodo`, monitor for 30 min
3. **Compare results:** 
   - Extraction success rate
   - Bot blocking incidents
   - Response times
   - Article quality

### Phase 2: A/B Testing (If Phase 1 shows improvement)

Deploy two processor instances:
- 50% traffic → Origin proxy
- 50% traffic → Decodo proxy

Monitor for 24 hours and compare metrics.

### Phase 3: Full Cutover (If Decodo wins)

```bash
# Permanently switch to Decodo
kubectl set env deployment/mizzou-processor -n production PROXY_PROVIDER=decodo

# Remove old origin proxy credentials (optional)
kubectl delete secret origin-proxy-credentials -n production
```

---

## Expected Outcomes

### If Decodo Solves Bot Blocking
- ✅ Extraction success rate > 70%
- ✅ Reduced bot blocking errors
- ✅ Faster extraction times
- ✅ More consistent results

**Next Step:** Keep using Decodo, monitor costs

### If Decodo Still Gets Blocked
- ❌ Similar bot blocking as origin proxy
- ❌ No improvement in success rate

**Next Step:** Try premium service (BrightData/ScraperAPI) or implement Selenium/JS rendering

---

## Monitoring

### Health Check

```bash
# Check proxy status
kubectl exec -n production deployment/mizzou-processor -- \
  python -m src.cli.cli_modular proxy status

# Expected output:
# Active Provider: decodo
# Status: enabled
# URL: http://user-sp8z2fzi1e-country-us:***@isp.decodo.com:10000
# Health: (will build over time)
```

### Success Rate Tracking

The ProxyManager automatically tracks:
- Request count
- Success count
- Failure count
- Success rate (%)
- Average response time

View with: `proxy status` command

---

## Troubleshooting

### Issue: Connection Timeout

```bash
# Check if proxy is reachable
kubectl exec -n production deployment/mizzou-processor -- \
  python3 test_decodo_proxy.py
```

### Issue: Still Getting Bot Blocked

If extractions still fail:
1. Verify it's actually using Decodo: `kubectl get env PROXY_PROVIDER`
2. Check logs for proxy connection errors
3. Try different provider (BrightData/ScraperAPI)

### Issue: Slow Response Times

If response time > 5 seconds:
1. Check proxy health: `proxy status`
2. Test direct connection: `PROXY_PROVIDER=direct`
3. Compare with origin: `PROXY_PROVIDER=origin`

---

## Next Steps

1. ✅ **Immediate:** Test Decodo proxy with `PROXY_PROVIDER=decodo`
2. ⏳ **Monitor:** Watch extraction success rate for 30 minutes
3. 🔍 **Compare:** Evaluate Decodo vs Origin proxy performance
4. 📊 **Decide:** 
   - If better → Keep using Decodo
   - If same → Try premium service (BrightData)
   - If worse → Stick with origin

---

## Cost Considerations

**Decodo Pricing:** Unknown (need to verify subscription details)

**Current Usage:** ~0.9 GB/month bandwidth

If Decodo is paid service, compare cost to:
- Origin proxy: ~$2-6/month
- ScraperAPI: $49-249/month
- BrightData: $500+/month

**Recommendation:** If Decodo costs more than $50/month and doesn't significantly improve success rate, may not be worth it. Premium services like ScraperAPI include JS rendering which may be more valuable.

---

## Conclusion

Decodo ISP proxy is now configured and ready to test. It's a **residential ISP proxy** with built-in credentials, making it easy to test immediately.

**Quick command to test:**
```bash
kubectl set env deployment/mizzou-processor -n production PROXY_PROVIDER=decodo
```

Monitor extraction success rate and compare to origin proxy to determine if it's worth keeping.
