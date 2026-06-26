# Quick Reference: Bot Protection Escalation

## TL;DR
We implemented 3 tactics to bypass bot protections blocking 26 sites. Expected 25-40% extraction improvement.

| Tactic | Problem | Solution | Target Sites | Expected Result |
|--------|---------|----------|--------------|-----------------|
| CloudScraper Escalation | Cloudflare JS challenge slow | Try cloudscraper before Selenium | kspr.com | ⚡ 5-10x faster (2-5s vs 15-30s) |
| Proxy Rotation | DNS/network errors | Auto-rotate proxies on connection error | 8 sites | ✅ Now succeeds (was 0%) |
| CAPTCHA Backoff | CAPTCHA blocks all attempts | Exponential backoff (10-90 min) | www.417mag.com | ✅ Graceful retry |

## Deployment

```bash
# Deploy
./scripts/deploy-services.sh main processor

# Monitor (watch logs for escalation events)
kubectl logs -n production deployment/mizzou-processor -f | grep ESCALATION
```

## Validation

**Check in 24-48 hours**:
```bash
# Expect these to improve:
# - kspr.com: 0% → 50%+ extraction success
# - DNS sites: 0% → 20-40% extraction success  
# - www.417mag.com: 0% → graceful backoff + retry

# Query extraction rates
kubectl exec -n production deployment/mizzou-api -- python -c "
from src.models.database import DatabaseManager
from sqlalchemy import text
# Check extraction success rates on problematic sites
"
```

## Expected Log Output

### ✅ CloudScraper Success
```
🚀 ESCALATION: kspr.com has Cloudflare protection - trying cloudscraper before Selenium
✅ Successfully fetched 45230 bytes from kspr.com
```

### ✅ Proxy Rotation Success  
```
🚀 ESCALATION: Connection error for www.griffononfm.com - Marking for proxy rotation
Escalated proxy for www.griffononfm.com: proxy1.com → proxy2.com
```

### ✅ CAPTCHA Backoff
```
Bot protection detected and all fallbacks failed for www.417mag.com
CAPTCHA backoff for www.417mag.com: 600s (attempt 1)
[30 minutes later...]
CAPTCHA backoff for www.417mag.com: 1200s (attempt 2)
```

## Rollback (if issues)

```bash
# 1-click rollback
kubectl rollout undo deployment/mizzou-processor -n production

# Check status
kubectl rollout status deployment/mizzou-processor -n production
```

## Files Modified

- `src/crawler/__init__.py` - 3 changes:
  1. CloudScraper escalation logic (~2295-2320)
  2. Proxy rotation method (~1137-1180)
  3. Exception handlers (newspaper ~3495, beautifulsoup ~3726)

## Key Metrics to Watch

| Metric | Baseline | Target | Status |
|--------|----------|--------|--------|
| Extraction issues in health check | 26 | < 15 | TBD (post-deployment) |
| kspr.com extraction success | 0% | 50%+ | TBD |
| DNS-error sites success | 0% | 20-40% | TBD |
| www.417mag.com backoff active | N/A | Yes | TBD |
| Processor CPU usage | Baseline | +10-15% OK | TBD |

## Questions?

- **CloudScraper not working?** Check if cloudscraper is installed: `pip list | grep cloudscraper`
- **Proxies failing?** Check proxy URL in logs: `kubectl logs ... | grep "proxy_url"`
- **Still failing?** Check protection type detection: `kubectl logs ... | grep "protection"`

## Team Contacts

- Escalation strategy: Copilot analysis
- Deployment: DevOps team
- Monitoring: Analytics/Operations team

---

**Deployment Date**: [To be filled]
**Deployed By**: [To be filled]  
**Status**: Ready to deploy ✅
