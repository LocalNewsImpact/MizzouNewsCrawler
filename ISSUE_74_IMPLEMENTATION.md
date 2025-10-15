# Issue #74 Implementation: Job-per-Dataset Architecture & Single-Domain Detection

## Summary

Implemented smart single-domain dataset detection and improved rate limiting for job-per-dataset extraction workflows.

## Problem Addressed

The Lehigh Valley News extraction job was hitting rate limits because:
1. The dataset contains only ONE domain (lehighvalleynews.com)
2. The system couldn't effectively rotate between domains
3. Rate limiting was reactive (per-batch) rather than proactive

## Solution Implemented

### 1. Upfront Domain Analysis

Added `_analyze_dataset_domains()` function that:
- Analyzes candidate links BEFORE extraction begins
- Counts unique domains in the dataset
- Identifies single-domain datasets proactively
- Samples up to 1000 URLs for accurate domain diversity assessment

**Key Code Changes:**
- Location: `src/cli/commands/extraction.py`
- New function: `_analyze_dataset_domains(args, session)`
- Returns: `{unique_domains: int, is_single_domain: bool, sample_domains: list}`

### 2. Improved Batch Sleep Logic

Enhanced the batch sleep decision to prioritize upfront analysis:

**Before:**
```python
# Only checked domains processed in current batch
needs_long_pause = (
    same_domain_consecutive >= max_same_domain or unique_domains <= 1
)
```

**After:**
```python
# Checks upfront detection FIRST, then falls back to batch analysis
needs_long_pause = (
    is_single_domain_dataset or                    # NEW: Upfront detection
    same_domain_consecutive >= max_same_domain or 
    unique_domains <= 1
)
```

### 3. Better User Feedback

**Console Output Now Shows:**
```
📊 Dataset analysis: 1 unique domain(s)
⚠️  Single-domain dataset detected: lehighvalleynews.com
🐌 Rate limiting will be conservative to avoid bot detection
```

**And warns if misconfigured:**
```
WARNING: Single-domain dataset detected but BATCH_SLEEP_SECONDS is low (5.0s). 
Consider increasing to 60-300s to avoid rate limiting.
```

**During batch processing:**
```
⏸️  Single-domain dataset - waiting 300s...
```

## Testing

### Unit Tests Added

Three new test cases in `tests/cli/commands/test_extraction.py`:

1. **`test_analyze_dataset_domains_single_domain`**
   - Verifies detection of single-domain datasets
   - Confirms `is_single_domain` flag is set correctly

2. **`test_analyze_dataset_domains_multiple_domains`**
   - Verifies detection of multi-domain datasets
   - Confirms domain list is correctly sampled

3. **`test_analyze_dataset_domains_no_urls`**
   - Handles edge case of empty dataset
   - Returns safe defaults

### Integration Testing

Tested with Lehigh extraction job configuration:
- Dataset: `Penn-State-Lehigh`
- Domain: `lehighvalleynews.com` (single domain)
- Expected behavior: Conservative rate limiting applied automatically

## Configuration Guidelines

### For Single-Domain Datasets (Like Lehigh)

**Recommended Environment Variables:**

```yaml
env:
  # Conservative inter-request timing
  - name: INTER_REQUEST_MIN
    value: "90.0"  # 90 seconds minimum between requests
  - name: INTER_REQUEST_MAX
    value: "180.0"  # 180 seconds maximum (3 minutes)
  
  # Long batch sleep to avoid pattern detection
  - name: BATCH_SLEEP_SECONDS
    value: "300"  # 5 minutes between batches
  - name: BATCH_SLEEP_JITTER
    value: "0.45"  # Add ±45% randomness
  
  # Reduced batch size
  - name: BATCH_SIZE_JITTER
    value: "0.33"  # Vary batch size by ±33%
  
  # User agent rotation
  - name: UA_ROTATE_BASE
    value: "4"  # Rotate every 3-5 requests
  - name: UA_ROTATE_JITTER
    value: "0.25"
  
  # IP rotation (if using proxy like Decodo)
  - name: DECODO_ROTATE_IP
    value: "true"
```

### For Multi-Domain Datasets

**Recommended Environment Variables:**

```yaml
env:
  # Faster timing (domain rotation provides natural rate limiting)
  - name: INTER_REQUEST_MIN
    value: "10.0"  # 10 seconds minimum
  - name: INTER_REQUEST_MAX
    value: "30.0"  # 30 seconds maximum
  
  # Short batch sleep (or minimal)
  - name: BATCH_SLEEP_SECONDS
    value: "5.0"  # 5 seconds between batches
  - name: INTER_BATCH_MIN_PAUSE
    value: "5.0"  # Minimal pause when rotating domains
```

## Benefits

### 1. Proactive Detection
- Identifies single-domain datasets BEFORE processing
- No need to learn through failed batches
- Immediate feedback to operators

### 2. Automatic Configuration
- System self-adjusts based on domain diversity
- Reduces manual configuration errors
- Prevents rate limit issues proactively

### 3. Better Observability
- Clear logging of domain analysis
- Visible warnings for misconfiguration
- Easier troubleshooting

### 4. Cost Savings
- Fewer failed requests due to rate limiting
- Less wasted compute time on blocked IPs
- Reduced need for manual intervention

## Files Modified

1. **`src/cli/commands/extraction.py`**
   - Added `_analyze_dataset_domains()` function
   - Enhanced `handle_extraction_command()` with upfront analysis
   - Improved batch sleep decision logic
   - Better console output and warnings

2. **`tests/cli/commands/test_extraction.py`**
   - Added 3 unit tests for domain analysis
   - Coverage for single-domain, multi-domain, and empty cases

3. **`k8s/templates/README.md`**
   - Added "Single-Domain Datasets (Rate Limiting)" section
   - Configuration examples
   - Monitoring commands
   - Troubleshooting guidance

4. **`ISSUE_74_IMPLEMENTATION.md`** (this file)
   - Comprehensive implementation documentation

## Deployment

### For Existing Jobs (e.g., Lehigh)

The single-domain detection is **automatic** - no code changes needed to existing jobs. The system will:

1. Detect single domain on startup
2. Apply conservative rate limiting automatically
3. Warn if `BATCH_SLEEP_SECONDS` is too low

### Recommended Action

Review and update `k8s/lehigh-extraction-job.yaml` to ensure:
- `BATCH_SLEEP_SECONDS >= 300` (5 minutes)
- `INTER_REQUEST_MIN >= 90` (90 seconds)
- `BATCH_SLEEP_JITTER >= 0.4` (40% randomness)

Current Lehigh configuration already has appropriate values:
```yaml
- name: INTER_REQUEST_MIN
  value: "90.0"  # ✅ Good
- name: INTER_REQUEST_MAX
  value: "180.0"  # ✅ Good
- name: BATCH_SLEEP_SECONDS
  value: "420.0"  # ✅ Good (7 minutes)
- name: BATCH_SLEEP_JITTER
  value: "0.45"  # ✅ Good
```

## Monitoring

### Check Domain Detection

```bash
# Watch for domain analysis output
kubectl logs -n production -l dataset=Penn-State-Lehigh --follow | grep "Dataset analysis\|Single-domain"
```

### Monitor Rate Limiting

```bash
# Watch for batch sleep messages
kubectl logs -n production -l dataset=Penn-State-Lehigh --follow | grep "⏸️"

# Check for rate limit warnings
kubectl logs -n production -l dataset=Penn-State-Lehigh --follow | grep "rate limit"
```

### Verify Configuration

```bash
# Get current environment variables
kubectl get job extract-penn-state-lehigh -n production -o jsonpath='{.spec.template.spec.containers[0].env[*]}' | jq
```

## Future Enhancements

### Potential Improvements (Out of Scope for Issue #74)

1. **Database-Stored Domain Analysis**
   - Cache domain analysis results in `datasets` table
   - Add `domain_count` and `primary_domains` columns
   - Skip analysis on repeated job runs

2. **Per-Domain Rate Limit Tracking**
   - Store rate limit encounters per domain
   - Exponential backoff for problematic domains
   - Persistent cooldown state across jobs

3. **Adaptive Rate Limiting**
   - Learn optimal timing from successful extractions
   - Adjust parameters based on 429 responses
   - Machine learning for bot detection avoidance

4. **CronJob Integration**
   - Auto-generate CronJobs for datasets
   - Schedule based on domain count (single-domain = less frequent)
   - Smart scheduling to avoid peak traffic times

## Related Issues

- **Issue #66**: Dataset-Specific Job Orchestration (foundation)
- **Issue #74**: Job-per-dataset architecture migration plan (this implementation)
- **Lehigh Job**: `k8s/lehigh-extraction-job.yaml` (primary use case)

## Success Metrics

### Pre-Implementation (Lehigh Job Issues)
- ❌ Frequent rate limiting (429 errors)
- ❌ Manual configuration required
- ❌ No visibility into domain diversity
- ❌ Reactive problem detection

### Post-Implementation (Expected)
- ✅ Automatic single-domain detection
- ✅ Proactive rate limiting configuration
- ✅ Clear visibility in logs
- ✅ Reduced rate limit errors
- ✅ Better operator guidance

## Rollout Plan

### Phase 1: Deploy Code (Current)
- ✅ Code changes implemented
- ✅ Tests added
- ✅ Documentation updated
- ⏳ Ready for PR merge

### Phase 2: Monitor Lehigh Job
- Watch first Lehigh extraction job with new code
- Verify domain detection works correctly
- Confirm rate limiting is appropriate
- Check for any warnings or errors

### Phase 3: Apply to Other Single-Domain Datasets
- Identify other single-domain datasets
- Review their configurations
- Apply lessons learned from Lehigh

### Phase 4: Scale Out (Optional)
- Consider implementing database-stored analysis
- Add CronJob auto-generation
- Build adaptive rate limiting system

## Conclusion

This implementation addresses the core issue from #74: **the system now intelligently detects single-domain datasets and automatically applies appropriate rate limiting strategies**. The Lehigh extraction job (and future single-domain jobs) will benefit from:

- Proactive detection
- Automatic configuration adjustment
- Better observability
- Reduced operational overhead

The job-per-dataset architecture from Issue #66 provides the foundation, and this enhancement makes it even more robust for challenging extraction scenarios like aggressive bot protection on single-domain publishers.
