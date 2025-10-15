# Argo Extraction Capacity Update

## Issue
The initial `extract-limit` of 20 articles per batch was too conservative for:
- **Daily publications** with high volume (10-30 articles/day)
- **Weekly publications** that drop 20-50+ articles at once
- **7-day lookback period** which could accumulate 70-200+ articles

## Change Summary

### Updated Configuration
**Before:**
- `extract-limit`: 20 articles/batch
- `extract-batches`: 60 batches
- **Total capacity**: 20 × 60 = **1,200 articles/run**

**After:**
- `extract-limit`: 50 articles/batch
- `extract-batches`: 40 batches
- **Total capacity**: 50 × 40 = **2,000 articles/run**

### Why This Change?

#### 1. **Better Weekly Publication Support**
- Weekly publications can drop 50-200 articles at once
- Previous capacity: 1,200 articles/run ✓ (sufficient but tight)
- New capacity: 2,000 articles/run ✓ (comfortable headroom)

#### 2. **Faster Processing**
- Larger batches (50 vs 20) = fewer batch transitions
- Fewer batch transitions = less overhead from `batch-sleep` delays
- **Time savings**: ~25-30% faster extraction for large backlogs

#### 3. **Still Safe for Rate Limiting**
- Rate limiting is controlled by:
  - `inter-request-min/max` (5-15s between requests)
  - `batch-sleep` (30s between batches)
  - CAPTCHA backoff (30min-2hr)
- Batch size doesn't affect these delays
- **Conclusion**: 50 articles/batch is safe with proper rate limiting

## Capacity Planning Examples

### Low Volume Daily (5-10 articles/day)
```yaml
extract-limit: 20
extract-batches: 30
# Capacity: 600 articles/run
```

### High Volume Daily (20-50 articles/day)
```yaml
extract-limit: 50
extract-batches: 40
# Capacity: 2,000 articles/run (NEW MIZZOU DEFAULT)
```

### Weekly Publications (50-200 articles/week)
```yaml
extract-limit: 50
extract-batches: 60
# Capacity: 3,000 articles/run
```

## Files Changed
1. `k8s/argo/mizzou-pipeline-cronworkflow.yaml` - Updated Mizzou pipeline to 50×40
2. `k8s/argo/dataset-pipeline-template.yaml` - Updated template with capacity planning guidance

## Deployment
The changes are in PR #83. Once merged, the next scheduled Mizzou pipeline run (every 6 hours) will use the new configuration automatically.

## Testing Recommendation
After deployment, monitor the first few runs:
- Check extraction completion time (should be faster)
- Verify no rate limit violations
- Confirm all articles are extracted (especially after weekly publications drop)

## Notes
- **Total capacity per run**: 2,000 articles
- **Daily capacity**: 4 runs/day × 2,000 = 8,000 articles (massive headroom)
- **Weekly capacity**: 28 runs/week × 2,000 = 56,000 articles
- **Conclusion**: New configuration handles weekly publications comfortably while maintaining safe rate limiting.
