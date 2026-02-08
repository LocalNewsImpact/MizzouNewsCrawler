# Bot Protection Escalation - Deployment Guide

## Quick Summary

We've implemented **three bot protection escalation tactics** to improve extraction success for 26 problematic sites:

1. **CloudScraper Escalation** - Try cloudscraper before Selenium for Cloudflare-protected sites (kspr.com)
2. **Proxy Rotation** - Auto-rotate proxies when DNS/network errors occur (8 sites)
3. **CAPTCHA Backoff** - Exponential backoff for CAPTCHA detection (www.417mag.com)

**Expected impact**: 25-40% improvement in extraction success for the 26 currently-failing sites.

## Files Changed

```
src/crawler/__init__.py
  - Lines ~1137-1180: Added _handle_connection_error_with_proxy_escalation() method
  - Lines ~2295-2320: Added CloudScraper escalation logic
  - Line ~3495: Integrated proxy escalation into newspaper exception handler
  - Line ~3726: Integrated proxy escalation into beautifulsoup exception handler
```

## Deployment Steps

### 1. Build Docker Image

```bash
# Build the crawler/processor image (includes crawling logic)
./scripts/deploy-services.sh main processor

# Or build API if also changed
./scripts/deploy-services.sh main api processor
```

### 2. Verify Changes (Optional)

Before deploying, test locally:

```bash
# Run extraction tests to verify no regressions
make test-unit  # Fast unit tests
# Or run integration tests
make test-postgres  # Full integration with PostgreSQL
```

### 3. Deploy to GKE

The build script above will automatically:
1. Trigger Cloud Build (build containers)
2. Push to Artifact Registry
3. Create Cloud Deploy release
4. Rollout to GKE production

Monitor deployment:

```bash
# Watch rollout progress
kubectl rollout status deployment/mizzou-processor -n production -w

# Check pod status
kubectl get pods -n production -l app=mizzou-processor

# View logs
kubectl logs -n production deployment/mizzou-processor --tail=100 -f
```

### 4. Manual Rollback (if needed)

```bash
# Rollback to previous deployment
kubectl rollout undo deployment/mizzou-processor -n production

# Verify rollback
kubectl rollout status deployment/mizzou-processor -n production
```

## Validation (24-48 hours post-deployment)

### 1. Check Extraction Success Rate

```bash
# Query BigQuery for extraction rate improvement
kubectl exec -n production deployment/mizzou-api -- python -c "
from src.models.database import DatabaseManager
from sqlalchemy import text
db = DatabaseManager()
with db.get_session() as session:
    # Check the 26 problematic sites
    problematic_sites = [
        'kspr.com',
        'www.417mag.com',
        'www.griffononfm.com',
        'mycameronb.com',
        'www.greenfield-online.com',
        'www.thesalemissourian.com',
        'www.newsonlinemissouri.com',
        'www.stegenholmissouri.com',
        'www.thebranson.news',
        'www.lincolnnewsgazette.com',
    ]
    
    result = session.execute(text(f'''
        SELECT cl.source, 
               COUNT(DISTINCT cl.id) as discovered_7d,
               COUNT(DISTINCT a.id) as extracted_7d,
               ROUND(100.0 * COUNT(DISTINCT a.id) / NULLIF(COUNT(DISTINCT cl.id), 0), 1) as success_rate
        FROM candidate_links cl
        LEFT JOIN articles a ON a.candidate_link_id = cl.id
        WHERE cl.discovered_at >= NOW() - INTERVAL '7 days'
        AND cl.source IN ({', '.join(f\"'{s}'\" for s in problematic_sites[:5])})
        GROUP BY cl.source
        ORDER BY success_rate ASC
    ''')).fetchall()
    
    print('Site                               | Discovered | Extracted | Success %')
    print('-' * 75)
    for row in result:
        print(f'{row[0]:35} | {row[1]:10} | {row[2]:9} | {row[3]:8}%')
"
```

### 2. Check Logs for Escalation Events

```bash
# Look for escalation strategy activations
kubectl logs -n production deployment/mizzou-processor --tail=1000 | grep ESCALATION

# Expected output:
# 🚀 ESCALATION: kspr.com has Cloudflare protection - trying cloudscraper before Selenium
# 🚀 ESCALATION: Connection error for www.griffononfm.com - Marking for proxy rotation
```

### 3. Monitor Pod Health

```bash
# Check for crashes or errors
kubectl describe pod -n production deployment/mizzou-processor
kubectl get events -n production --sort-by='.lastTimestamp' | tail -20
```

### 4. Check Weekly Health Report

The next weekly health check (Monday 6 AM UTC) should show:
- Fewer extraction issues (currently 26)
- Different sites may appear if they were masking other problems
- CAPTCHA sites may show as "active backoff" status

## Rollback Decision Points

**Rollback if**:
1. Pod crashes or enters CrashLoopBackOff
2. Extraction success rate DECREASES (regression)
3. Error rates spike above 10% in logs
4. API response times degrade >50%

**Don't rollback if**:
- High CPU/memory: Expected during aggressive retry logic
- Elevated network traffic: Expected with proxy rotation
- Exponential backoff delays: Expected for CAPTCHA sites

## Key Logging to Watch

### CloudScraper Escalation (Expected)
```
🚀 ESCALATION: kspr.com has Cloudflare protection - trying cloudscraper before Selenium
[EXTRACTION ESCALATION] kspr.com: cloudflare_bypass=cloudscraper, proxy_rotation=enabled, captcha_backoff=exponential
✅ Successfully fetched 45230 bytes from kspr.com via CloudScraper
```

### Proxy Rotation (Expected for DNS errors)
```
🚀 ESCALATION: Connection error for www.griffononfm.com - Marking for proxy rotation
Rotating proxy for www.griffononfm.com due to connection error
Escalated proxy for www.griffononfm.com: http://proxy1.com → http://proxy2.com
```

### CAPTCHA Backoff (Expected)
```
Bot protection detected and all fallbacks failed for www.417mag.com
CAPTCHA backoff for www.417mag.com: 600s (attempt 1)
CAPTCHA backoff for www.417mag.com: 1200s (attempt 2)  [30 min later]
```

## Performance Expectations

| Scenario | Before | After | Change |
|----------|--------|-------|--------|
| Cloudflare site (kspr.com) | Selenium 15-30s | CloudScraper 2-5s | ⚡ 5-10x faster |
| DNS error site | Fail (0s) | Proxy retry 5-10s | ✅ Now works |
| CAPTCHA site | Fail (0s) | Backoff 10-90 min | ✅ Auto-retry |
| Normal site | 2-5s | 2-5s | ➡️ No change |

## Monitoring Dashboard

### Recommended Grafana Queries

```
# Extraction success rate by source
rate(articles_extracted_total[5m]) / rate(candidate_links_discovered_total[5m])

# CloudScraper bypass events
rate(cloudflare_escalation_attempts_total[5m])

# Proxy rotation events
rate(proxy_rotation_events_total[5m])

# CAPTCHA backoff events
rate(captcha_backoff_applied_total[5m])
```

## Rollback Procedure

If immediate rollback needed:

```bash
# Option 1: Immediate rollback to previous revision
kubectl rollout undo deployment/mizzou-processor -n production
kubectl rollout status deployment/mizzou-processor -n production

# Option 2: Rollback to specific revision
kubectl rollout history deployment/mizzou-processor -n production
kubectl rollout undo deployment/mizzou-processor -n production --to-revision=3

# Verify success
kubectl get pods -n production -l app=mizzou-processor
```

## Post-Deployment Checklist

- [ ] Build completed successfully (Cloud Build)
- [ ] Image pushed to Artifact Registry
- [ ] Cloud Deploy release created
- [ ] GKE rollout completed
- [ ] Pods healthy (ready: 1/1)
- [ ] Logs show no errors in first 5 min
- [ ] Escalation events appearing in logs (24h check)
- [ ] BigQuery shows extraction rate improvement (48h check)
- [ ] Weekly health check shows improvement (7 day check)

## Questions/Issues

If deployment has issues:

1. **Pods crashing**: Check logs for syntax errors or import issues
   ```bash
   kubectl logs -n production <pod-name> --previous
   ```

2. **No escalation events**: Check if sites are being processed
   ```bash
   # Count articles in queue
   kubectl exec -n production deployment/mizzou-processor -- python -m src.cli.cli_modular pipeline-status --hours 24
   ```

3. **Extraction still failing**: May need different proxy providers or additional retries
   - Check CAPTCHA/bot protection detection in logs
   - Verify proxy URLs are valid
   - Consider implementing CAPTCHA solver

## Success Criteria

✅ **Deployment is successful if** (within 48 hours):

1. No pod crashes or CrashLoopBackOff
2. Extraction success rate for CloudFlare site (kspr.com) > 0% (was 0%)
3. At least 1-2 DNS-error sites show improved extraction
4. Weekly health check shows < 20 extraction issues (down from 26)
5. No increase in general error rate

🎯 **Target**: 25-40% improvement in extraction success for the 26 problematic sites.

---

**Deployment Date**: [Insert deployment date]
**Deployed By**: [Your name]
**Deployment Ticket**: [Link to issue/PR]
