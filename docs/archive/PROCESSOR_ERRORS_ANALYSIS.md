# Processor Errors Analysis - October 8, 2025

## Summary
Three critical error categories identified in production processor logs:

1. **Entity Extraction SQL Error** - FIXED ✅
2. **ML Analysis Proxy Authentication Error** - NEEDS FIX ❌
3. **Extraction Bot Detection/CAPTCHA Errors** - NEEDS FIX ❌

---

## 1. Entity Extraction SQL Error ✅ FIXED

### Error Message
```
column a.source_id does not exist
```

### Root Cause
The entity extraction query was trying to select `a.source_id` and `a.dataset_id` directly from the `articles` table, but these columns don't exist there. They exist in the `candidate_links` table.

### Fix Applied
Changed the SQL query in `src/cli/commands/entity_extraction.py` to join with `candidate_links`:

```sql
-- OLD (broken):
SELECT a.id, a.text, a.text_hash, a.source_id, a.dataset_id
FROM articles a
WHERE ...

-- NEW (fixed):
SELECT a.id, a.text, a.text_hash, cl.source_id, cl.dataset_id
FROM articles a
JOIN candidate_links cl ON a.candidate_link_id = cl.id
WHERE ...
```

### Status
- ✅ Fixed in commit c0d693b
- ⏳ Needs deployment to production
- 📊 Impact: 1,538 articles pending entity extraction

---

## 2. ML Analysis Proxy Authentication Error ❌ NEEDS FIX

### Error Message
```
407 Client Error: PROXY AUTHENTICATION REQUIRED 
for url: http://proxy.kiesow.net:23432/?url=https%3A%2F%2Fhuggingface.co%2Fdistilbert-base-uncased-finetuned-sst-2-english%2Fresolve%2Fmain%2Fconfig.json
```

### Root Cause
HuggingFace model downloads are being routed through the proxy, but HuggingFace requires authentication. The proxy is rejecting the request with 407 error.

### Impact
- 1,406 articles pending ML classification
- ML analysis pipeline completely blocked
- Cannot load the DistilBERT model from HuggingFace

### Recommended Fix
Add HuggingFace domains to the proxy bypass list:

1. **Check current bypass list**:
   ```bash
   kubectl exec -n production deploy/mizzou-processor -- env | grep -i proxy
   ```

2. **Update NO_PROXY environment variable** in processor deployment to include:
   - `huggingface.co`
   - `*.huggingface.co`
   - `cdn-lfs.huggingface.co`

3. **Update k8s/processor-deployment.yaml**:
   ```yaml
   env:
     - name: NO_PROXY
       value: "localhost,127.0.0.1,metadata.google.internal,huggingface.co,*.huggingface.co,cdn-lfs.huggingface.co"
   ```

### Alternative Solutions
- Pre-download the model into the container image during build
- Use a local model path that's already cached
- Configure proxy authentication for HuggingFace

---

## 3. Extraction Bot Detection/CAPTCHA Errors ❌ NEEDS FIX

### Affected Domains
Based on log analysis:

1. **www.fultonsun.com**
   - CAPTCHA detected
   - Backoff: 642s
   - Status: Cannot extract content

2. **www.ozarksfirst.com**
   - Bot detection (403)
   - Rate limited
   - Backoff: 120s
   - Status: Domain failed 2 times, skipped batch

3. **www.maryvilleforum.com**
   - CAPTCHA detected
   - Backoff: 665s
   - Additional issue: gzip decompression error
   - Status: Cannot extract content

4. **www.theprospectnews.com**
   - 404 Not Found (permanent)
   - Less critical - content may have been removed

### Error Patterns

#### Pattern 1: CAPTCHA Detection
```
CAPTCHA or challenge detected on [URL]
CAPTCHA backoff for [domain]: [time]s (attempt [N])
Could not extract fields [...] for [URL] with any method
```

#### Pattern 2: Rate Limiting
```
Possible bot detection (403) by [domain]
Rate limited by [domain], backing off for [time]s (attempt [N])
Domain [domain] failed [N] times; skipping batch
```

#### Pattern 3: Technical Failures
```
Session fetch failed: Received response with content-encoding: gzip, 
but failed to decode it
```

### Impact
- 122 articles pending extraction
- Multiple domains with persistent failures
- Extraction pipeline blocked for these sources

### Recommended Fixes

#### Short-term (Emergency)
1. **Increase backoff times** for CAPTCHA domains
2. **Skip problematic domains** temporarily
3. **Use residential proxies** for bot-protected sites
4. **Add domain-specific headers** and user agents

#### Long-term (Robust)
1. **Implement domain-specific extractors**
   - Custom extraction logic per publisher
   - Pre-configured for known bot protections

2. **Use authenticated RSS feeds** where available
   - Some publishers provide API access
   - Reduce need for web scraping

3. **Rotating proxy pool**
   - Multiple proxy IPs
   - Rotate on rate limits
   - Residential proxies for tough domains

4. **Selenium with stealth plugins**
   - selenium-stealth to avoid detection
   - Browser fingerprint randomization
   - Slower but more reliable for protected sites

5. **Monitor domain health**
   - Track failure rates per domain
   - Auto-disable problematic domains
   - Alert when success rate drops

---

## Priority Recommendations

### High Priority (Deploy ASAP)
1. ✅ **Entity extraction SQL fix** - Already committed, needs deployment
2. ❌ **ML analysis proxy fix** - Blocking 1,406 articles

### Medium Priority (This Week)
3. ❌ **Extraction bot detection** - Blocking 122 articles from 4+ domains

### Low Priority (Future Enhancement)
4. Long-term extraction improvements (domain-specific extractors, proxy rotation)

---

## Deployment Plan

### Phase 1: SQL Fix (Immediate)
```bash
# Push SQL fix
git push origin feature/gcp-kubernetes-deployment

# Rebuild processor
gcloud builds triggers run build-processor-manual --branch=feature/gcp-kubernetes-deployment

# Wait for pod rollout
kubectl rollout status deployment/mizzou-processor -n production

# Test entity extraction
kubectl exec -n production deploy/mizzou-processor -- \
  python -m src.cli.cli_modular extract-entities --limit 10
```

### Phase 2: Proxy Fix (Within 2 hours)
```bash
# Edit processor deployment
kubectl edit deployment mizzou-processor -n production

# Add to env section:
# - name: NO_PROXY
#   value: "localhost,127.0.0.1,metadata.google.internal,huggingface.co,*.huggingface.co"

# Save and wait for rollout
kubectl rollout status deployment/mizzou-processor -n production

# Test ML analysis
kubectl exec -n production deploy/mizzou-processor -- \
  python -m src.cli.cli_modular analyze --limit 10
```

### Phase 3: Extraction Fix (Within 24 hours)
- Research domain-specific solutions
- Test with residential proxy service
- Implement domain exclusion list temporarily

---

## Testing Commands

### Verify Entity Extraction Fix
```bash
kubectl exec -n production deploy/mizzou-processor -- \
  python -m src.cli.cli_modular extract-entities --limit 50
```

### Verify ML Analysis Fix
```bash
kubectl exec -n production deploy/mizzou-processor -- \
  python -m src.cli.cli_modular analyze --limit 100
```

### Check Proxy Environment
```bash
kubectl exec -n production deploy/mizzou-processor -- \
  env | grep -E "(PROXY|proxy)"
```

### Monitor Processor Logs
```bash
kubectl logs -n production deploy/mizzou-processor -f | \
  grep -E "(ERROR|failed|CAPTCHA|407)"
```

---

## Related Issues
- Issue #57: Critical processor errors (entity extraction, proxy, extraction failures)
- PR #58: Pipeline visibility and monitoring (merged to feature branch)

## Files Modified
- ✅ `src/cli/commands/entity_extraction.py` - SQL fix
- ⏳ `k8s/processor-deployment.yaml` - Proxy bypass (pending)
