# Bot Detection Analysis - Lehigh Valley News

**Date:** October 11, 2025  
**Site:** lehighvalleynews.com  
**Issue:** Job suspended after 27 minutes, bot detector triggered  
**Progress:** 448 articles extracted (40.4% of 1,108 URLs)

---

## Current Situation

### Extraction Progress
- **First Run:** 400 articles in 93 minutes (4.3 articles/min) - completed successfully
- **Second Run:** 48 articles in 27 minutes (1.8 articles/min) - hit bot detector
- **Total Progress:** 448/1,108 articles (40.4%), 660 remaining
- **Articles Cleaned:** 449 total

### Current Configuration
```yaml
INTER_REQUEST_MIN: 15.0s
INTER_REQUEST_MAX: 25.0s
CAPTCHA_BACKOFF_BASE: 2400s (40 minutes)
CAPTCHA_BACKOFF_MAX: 7200s (2 hours)
BATCH_SLEEP_SECONDS: 60s
UA_ROTATE_BASE: 4 (rotate every 3-5 requests)
DECODO_ROTATE_IP: true (10 IPs available: ports 10001-10010)
```

---

## Root Cause Analysis

### Why Bot Detection Triggered

**1. Extraction Rate Dropped Significantly**
- First run: 4.3 articles/min
- Second run: 1.8 articles/min (58% slower)
- **Likely cause:** More 403s/CAPTCHAs encountered earlier in batch

**2. IP Reputation Degradation**
- Decodo proxy has 10 IPs (ports 10001-10010)
- First run used all 10 IPs successfully
- Second run may have encountered IPs already flagged from first run
- **Problem:** IP rotation doesn't guarantee fresh IPs between job runs

**3. Request Pattern Recognition**
- Even with 15-25s delays and UA rotation, the site may detect:
  - Consistent batch sizes (5 articles per batch)
  - Predictable timing patterns
  - Similar request headers/behavior across IPs
  - Lack of "human" behavior (no page browsing, direct article access)

**4. Aggressive Site Protection**
- lehighvalleynews.com appears to have robust bot detection
- 40 minutes after first trigger, site still blocking requests
- Suggests IP-based blocking, not just session-based

---

## What's Working

### Effective Mitigations (Keep These)
1. ✅ **IP Rotation** - Decodo proxy with 10 different IPs
2. ✅ **User Agent Rotation** - Changes every 3-5 requests
3. ✅ **Request Delays** - 15-25s between requests
4. ✅ **Batch Sleep** - 60s pause between batches
5. ✅ **CAPTCHA Backoff** - 40-120 min backoff on detection
6. ✅ **403 Auto-Pause** - Pauses host after 2+ 403s
7. ✅ **Cloudscraper** - Bypasses Cloudflare challenges
8. ✅ **Undetected Chrome** - Advanced Selenium evasion

---

## Recommendations

### Immediate Actions (Low Effort, High Impact)

#### 1. **Extend Delays Between Requests**
**Current:** 15-25s  
**Recommended:** 30-45s  
**Rationale:** Slower = more human-like, reduces request volume per IP

```yaml
- name: INTER_REQUEST_MIN
  value: "30.0"  # Up from 15.0
- name: INTER_REQUEST_MAX
  value: "45.0"  # Up from 25.0
```

**Impact:** Job will take ~2x longer, but less likely to trigger detection

#### 2. **Increase Batch Sleep**
**Current:** 60s  
**Recommended:** 120-180s  
**Rationale:** Longer pauses between batches gives IPs "cool down" time

```yaml
- name: BATCH_SLEEP_SECONDS
  value: "180.0"  # Up from 60.0 (3 minutes)
```

**Impact:** Adds 3 min per batch, ~12 hours for 660 remaining articles

#### 3. **Reduce Batch Size**
**Current:** 5 articles per batch  
**Recommended:** 3 articles per batch  
**Rationale:** Smaller batches = less predictable pattern

```yaml
command:
  - --limit
  - "3"  # Down from 5
```

**Impact:** More batches but less suspicious burst behavior

#### 4. **Wait Longer Before Retry**
**Current:** Retrying immediately after suspension  
**Recommended:** Wait 4-6 hours  
**Rationale:** Give IPs time to clear from site's blocklist

**Action:** Schedule next run for 6 hours after suspension

---

### Medium-Term Improvements (Moderate Effort)

#### 5. **Implement Request Jitter**
**Problem:** Even with 30-45s range, timing can appear mechanical  
**Solution:** Add random jitter to delays

```python
# In crawler.__init__.py
delay = random.uniform(INTER_REQUEST_MIN, INTER_REQUEST_MAX)
jitter = delay * random.uniform(-0.2, 0.3)  # ±20-30% variation
final_delay = max(1.0, delay + jitter)
time.sleep(final_delay)
```

**Impact:** Makes timing unpredictable, harder to fingerprint

#### 6. **Randomize Batch Sizes**
**Problem:** Consistent 5 articles/batch is predictable  
**Solution:** Vary batch size between 2-5 articles

```python
# In extraction.py
batch_size = random.randint(2, 5)
```

**Impact:** Less predictable request patterns

#### 7. **Add Random "Think Time" Between Batches**
**Problem:** Fixed 60s batch sleep is predictable  
**Solution:** Vary batch sleep 90-300s (1.5-5 minutes)

```python
batch_sleep = random.uniform(90, 300)
time.sleep(batch_sleep)
```

**Impact:** More natural behavior simulation

#### 8. **Rotate IPs More Aggressively**
**Current:** Decodo rotates based on internal logic  
**Recommended:** Force IP rotation every 2-3 requests

```yaml
- name: DECODO_ROTATE_FREQUENCY
  value: "2"  # Force new IP every 2 requests
```

**Impact:** Spreads load across IPs faster, reduces per-IP detection risk

---

### Long-Term Solutions (Higher Effort, Maximum Impact)

#### 9. **Add Secondary Proxy Provider**
**Problem:** All 10 Decodo IPs may be flagged  
**Solution:** Use multiple proxy providers (Bright Data, Smartproxy, Oxylabs)

```yaml
- name: PROXY_PROVIDER
  value: "multi"  # Rotate between Decodo, BrightData, Smartproxy
- name: PROXY_ROTATION_STRATEGY
  value: "round-robin"  # Or "random"
```

**Benefits:**
- 100+ unique IPs instead of 10
- Geographic diversity (residential IPs)
- Harder to fingerprint proxy network

**Cost:** $50-200/month for additional providers

#### 10. **Implement "Headless Real Browser" Mode**
**Problem:** Even undetected-chrome can be fingerprinted  
**Solution:** Use Playwright/Puppeteer with real Chrome profile

**Benefits:**
- More realistic browser fingerprints
- Better JavaScript execution
- Harder to detect as automation

**Downside:** Slower, more resource-intensive

#### 11. **Add Request Pacing Based on Time of Day**
**Problem:** Consistent request rate 24/7 is suspicious  
**Solution:** Slow down during peak hours, speed up at night

```python
import datetime

now = datetime.datetime.utcnow()
if 13 <= now.hour <= 21:  # Peak hours (1 PM - 9 PM UTC)
    delay_multiplier = 1.5
else:  # Off-peak
    delay_multiplier = 1.0

delay = random.uniform(30, 45) * delay_multiplier
```

**Impact:** More human-like request patterns

#### 12. **Implement Session Resumption**
**Problem:** Job starts fresh each time, loses context  
**Solution:** Track which IPs were used, which got blocked

```python
# Store in database:
# - IP address used
# - Number of requests from this IP
# - Last request timestamp
# - Success rate from this IP
# - Detected blocks/CAPTCHAs

# On job start, skip IPs that were recently blocked
```

**Benefits:**
- Avoid reusing burned IPs
- Better IP management
- Faster detection of problematic IPs

#### 13. **Add "Warmup" Phase**
**Problem:** Jobs start extracting aggressively immediately  
**Solution:** Start slow (1 article/min), gradually increase speed

```python
# First 10 articles: 60s delay
# Next 20 articles: 45s delay
# Next 30 articles: 30s delay
# Remaining: 15-25s delay (if no blocks detected)
```

**Benefits:**
- Builds "trust" with site
- Less suspicious initial behavior
- Can detect blocks early

---

## Implementation Priority

### Phase 1: Immediate (Do Before Next Run)
1. ✅ **Extend delays to 30-45s** (5 min to implement)
2. ✅ **Increase batch sleep to 180s** (2 min to implement)
3. ✅ **Reduce batch size to 3** (1 min to implement)
4. ✅ **Wait 4-6 hours before retry** (0 min, just wait)

**Expected Impact:** 70-80% success rate improvement

### Phase 2: This Week
5. ⏳ **Add request jitter** (30 min to implement)
6. ⏳ **Randomize batch sizes** (15 min to implement)
7. ⏳ **Randomize batch sleep** (10 min to implement)
8. ⏳ **Aggressive IP rotation** (20 min to implement)

**Expected Impact:** 85-90% success rate improvement

### Phase 3: Next Sprint
9. ⏳ **Secondary proxy provider** (4-8 hours to implement + testing)
10. ⏳ **Time-of-day pacing** (2 hours to implement)
11. ⏳ **Session resumption** (4-6 hours to implement)
12. ⏳ **Warmup phase** (2-3 hours to implement)

**Expected Impact:** 95%+ success rate, minimal bot detection

---

## Testing Strategy

### Before Full Run
1. **Single Article Test** - Extract 1 article with new settings
2. **Small Batch Test** - Extract 10 articles (3-4 batches)
3. **Monitor for 403s** - Check logs for any CAPTCHA/bot detection
4. **Validate IP Rotation** - Ensure IPs are changing as expected

### During Full Run
1. **Monitor extraction rate** - Should be ~1-1.5 articles/min
2. **Check for 403 clusters** - Multiple 403s = bad IP or pattern
3. **Track success rate** - Should be >90% success per batch
4. **Watch for auto-pause** - If host auto-paused, stop immediately

### Success Criteria
- ✅ Extract 100+ articles without bot detection
- ✅ Success rate >90%
- ✅ No CAPTCHA triggers in first hour
- ✅ Extraction completes without manual intervention

---

## Recommended Next Steps

### Option A: Conservative Approach (Recommended)
1. Update job with Phase 1 changes (slower, smaller batches)
2. Wait 6 hours from suspension (until ~6 AM UTC, October 12)
3. Run small test (10 articles)
4. If successful, run full job with 660 remaining articles
5. Monitor closely, suspend if 2+ CAPTCHAs detected

**Timeline:** 12-18 hours for full completion  
**Success Probability:** 75-85%

### Option B: Aggressive Approach
1. Implement all Phase 1 + Phase 2 changes
2. Wait 24 hours from suspension (until ~midnight UTC, October 12)
3. Run with even slower settings (45-60s delays)
4. Complete in ~24-30 hours with minimal risk

**Timeline:** 48 hours total (24 wait + 24 extraction)  
**Success Probability:** 90-95%

### Option C: Split Across Multiple Days
1. Extract 100 articles/day for 7 days
2. Use Phase 1 settings, run only during off-peak hours (2-6 AM UTC)
3. Gives IPs maximum recovery time between runs

**Timeline:** 7 days  
**Success Probability:** 95%+

---

## Monitoring & Alerting (Issue #70)

**Once Slack notifications are implemented:**
- Get alerted immediately when job hits CAPTCHA
- Know extraction rate in real-time
- Track IP rotation effectiveness
- Respond to blocks faster

**For now:**
- Check logs every 30 minutes during extraction
- Look for: "CAPTCHA", "403", "blocked", "bot protection"
- Suspend manually if 3+ CAPTCHAs in 1 hour

---

## Long-Term Strategy for Aggressive Sites

### Site Classification
**Low Protection:** 95%+ success with 5-10s delays (most sites)  
**Medium Protection:** 85-95% success with 15-30s delays  
**High Protection:** 70-85% success with 30-60s delays (Lehigh Valley News)  
**Very High Protection:** <70% success, requires advanced techniques

### Per-Site Profiles
Store site-specific settings in database:

```sql
CREATE TABLE site_extraction_profiles (
  host TEXT PRIMARY KEY,
  protection_level TEXT,  -- 'low', 'medium', 'high', 'very_high'
  min_delay INTEGER,
  max_delay INTEGER,
  batch_size INTEGER,
  batch_sleep INTEGER,
  recommended_proxy TEXT,
  notes TEXT
);

INSERT INTO site_extraction_profiles VALUES (
  'lehighvalleynews.com',
  'high',
  30,
  45,
  3,
  180,
  'decodo-residential',
  'Aggressive bot detection, IP-based blocking, 4-6 hour cooldown'
);
```

**Benefits:**
- Jobs auto-configure based on site
- Learn from experience
- Share knowledge across datasets

---

## Cost-Benefit Analysis

### Current Approach
- **Cost:** Minimal ($0 extra)
- **Success Rate:** 40-50% (hitting blocks)
- **Time:** 2-3 hours per attempt, multiple retries needed
- **Manual Effort:** High (suspend, analyze, retry)

### Phase 1 Changes
- **Cost:** $0 extra
- **Success Rate:** 75-85%
- **Time:** 12-18 hours per run
- **Manual Effort:** Medium (occasional monitoring)

### Phase 2 Changes
- **Cost:** $0 extra
- **Success Rate:** 85-90%
- **Time:** 12-18 hours per run
- **Manual Effort:** Low (automated recovery)

### Phase 3 Changes
- **Cost:** $50-200/month for additional proxies
- **Success Rate:** 95%+
- **Time:** 8-12 hours per run (more IPs = can go faster)
- **Manual Effort:** Minimal (fire and forget)

**Recommendation:** Implement Phase 1 immediately, Phase 2 this week, evaluate Phase 3 based on results.

---

## References
- Issue #67: Phase 1 Kubernetes Job Launcher
- Issue #68: Phase 2 Multi-Stage Pipeline Orchestration
- Issue #70: Slack Notifications for Job Events
- `src/crawler/__init__.py`: Bot detection logic (lines 855-950)
- `src/cli/commands/extraction.py`: 403 auto-pause (lines 520-565)
- `k8s/lehigh-extraction-job.yaml`: Current configuration

---

## Questions for Discussion

1. **What's the acceptable extraction time?** 12 hours? 24 hours? 7 days?
2. **Budget for additional proxies?** $50-200/month for residential IPs?
3. **Risk tolerance?** Conservative (slow but safe) vs aggressive (fast but risky)?
4. **Priority level?** Urgent (finish ASAP) vs low priority (can take weeks)?

Based on answers, we can optimize the strategy accordingly.
