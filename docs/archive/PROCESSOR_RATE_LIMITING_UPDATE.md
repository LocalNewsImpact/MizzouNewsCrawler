# Processor Rate Limiting Update - October 13, 2025

## Problem
The mizzou-processor deployment was hitting excessive bot detection and CAPTCHA challenges across multiple domains due to aggressive rate limiting settings.

### Bot Detection Evidence
Multiple domains triggered CAPTCHA backoffs within a short timeframe:
- `www.webstercountycitizen.com` (4 backoffs)
- `www.the-standard.org` (4 backoffs, sensitivity level 8)
- `www.kprs.com` (4 backoffs)
- `fox2now.com` (2 backoffs, px-captcha detected)
- `eldoradospringsmo.com` (sensitivity increased 5 → 8)
- 15+ additional domains with bot detection

## Root Cause
The processor was crawling **too aggressively** with settings designed for speed rather than stealth:

| Setting | Old Value | Problem |
|---------|-----------|---------|
| INTER_REQUEST_MIN | 15 seconds | Too fast, creates obvious bot pattern |
| INTER_REQUEST_MAX | 25 seconds | Too fast, creates obvious bot pattern |
| EXTRACTION_BATCH_SIZE | 20 articles | Large bursts flood single domains |
| BATCH_SLEEP_SECONDS | 60 seconds | Insufficient cooldown between batches |
| CAPTCHA_BACKOFF_BASE | 2,400s (40 min) | Too short for domain recovery |
| CAPTCHA_BACKOFF_MAX | 7,200s (2 hours) | Too short for persistent blocks |

## Solution Applied

### Updated Rate Limiting Configuration
Matched the conservative settings from the successful Lehigh Valley News extraction job:

| Setting | Old Value | New Value | Change |
|---------|-----------|-----------|--------|
| **INTER_REQUEST_MIN** | 15.0s | 90.0s | 6x slower |
| **INTER_REQUEST_MAX** | 25.0s | 180.0s | 7x slower |
| **EXTRACTION_BATCH_SIZE** | 20 | 10 | 50% smaller |
| **BATCH_SLEEP_SECONDS** | 60.0s | 420.0s (7 min) | 7x longer |
| **BATCH_SLEEP_JITTER** | N/A | 0.45 (45%) | NEW: ~231-609s range |
| **BATCH_SIZE_JITTER** | N/A | 0.20 (20%) | NEW: 8-12 articles |
| **CAPTCHA_BACKOFF_BASE** | 2,400s | 7,200s (2 hours) | 3x longer |
| **CAPTCHA_BACKOFF_MAX** | 7,200s | 21,600s (6 hours) | 3x longer |

### Bot Evasion Features
1. **Longer delays between requests**: 90-180 seconds (vs 15-25s)
2. **Smaller batch sizes**: 8-12 articles with jitter (vs fixed 20)
3. **Extended cooldown**: 7 minutes between batches (vs 1 minute)
4. **Randomization**: Jitter on both batch sizes and delays
5. **Longer CAPTCHA recovery**: 2-6 hour backoffs (vs 40min-2hr)
6. **Bot sensitivity tracking**: Preserves learned sensitivity levels per domain

### Unchanged Settings (Already Optimal)
- ✅ **Decodo proxy with IP rotation**: Enabled
- ✅ **User agent rotation**: Every 3-5 requests
- ✅ **Bot sensitivity manager**: Tracks and adjusts per-domain behavior
- ✅ **Image**: `processor:d0c043e` with 404 auto-detection

## Deployment Details

**File Modified**: `k8s/processor-deployment.yaml`

**Deployment Command**:
```bash
kubectl apply -f k8s/processor-deployment.yaml
```

**Verification**:
```bash
# Check pod status
kubectl get pods -n production -l app=mizzou-processor

# Verify environment variables
kubectl exec -n production deployment/mizzou-processor -- env | grep -E "(INTER_REQUEST|CAPTCHA|BATCH)"
```

## Expected Results

### Throughput Impact
- **Before**: ~20 articles per batch, every ~90 seconds = ~13 articles/min
- **After**: ~10 articles per batch, every ~10 minutes = ~1 article/min
- **Reduction**: ~92% slower extraction rate

### Bot Detection Impact
- Significantly reduced CAPTCHA challenges
- Longer recovery times prevent repeated blocks
- Randomization prevents pattern detection
- Bot sensitivity tracking improves over time

### Trade-offs
- ✅ **Pro**: Much lower bot detection rate
- ✅ **Pro**: More sustainable long-term crawling
- ✅ **Pro**: Better domain relationship preservation
- ⚠️ **Con**: Slower extraction throughput
- ⚠️ **Con**: Longer time to process full queue

## Monitoring

### Key Metrics to Watch
1. **CAPTCHA backoff frequency**: Should decrease dramatically
2. **Extraction success rate**: Should increase
3. **Bot sensitivity levels**: Should stabilize or decrease over time
4. **Queue depth**: May grow initially but will stabilize

### Log Monitoring
```bash
# Watch for CAPTCHA backoffs (should be rare)
kubectl logs -n production deployment/mizzou-processor --tail=200 | grep "CAPTCHA backoff"

# Check bot sensitivity adjustments
kubectl logs -n production deployment/mizzou-processor --tail=200 | grep "Bot detection"

# Monitor extraction rate
kubectl logs -n production deployment/mizzou-processor --tail=100 | grep "articles extracted"
```

## Comparison: Lehigh Job Success

The Lehigh Valley News extraction job using these same settings achieved:
- **865 articles extracted**
- **861 successfully classified** (99.5% success rate)
- **100% dual-label coverage** (primary + alternate labels)
- **Minimal bot detection** on a site with sensitivity level 10 (very aggressive)

## Rollback Plan

If issues arise, revert to previous settings:

```yaml
# Aggressive settings (old configuration)
INTER_REQUEST_MIN: "15.0"
INTER_REQUEST_MAX: "25.0"
EXTRACTION_BATCH_SIZE: "20"
BATCH_SLEEP_SECONDS: "60.0"
CAPTCHA_BACKOFF_BASE: "2400"
CAPTCHA_BACKOFF_MAX: "7200"
# Remove BATCH_SLEEP_JITTER and BATCH_SIZE_JITTER
```

Then reapply:
```bash
kubectl apply -f k8s/processor-deployment.yaml
```

## Related Changes

- **Batch size jitter code**: Added to `src/cli/commands/extraction.py`
  - Supports `BATCH_SIZE_JITTER` environment variable
  - Randomizes articles per batch around base value
  - Prevents predictable batch size patterns

- **Lehigh extraction job**: `k8s/lehigh-extraction-job.yaml`
  - Updated to `processor:d0c043e`
  - 3 articles per batch with 33% jitter
  - Same conservative rate limiting

## Conclusion

The processor has been updated with conservative, bot-friendly rate limiting that matches the proven successful configuration from the Lehigh extraction job. This should dramatically reduce bot detection while maintaining sustainable extraction throughput.

**Status**: ✅ Deployed and running as of October 13, 2025
**Pod**: `mizzou-processor-55f478fb77-msd5f`
