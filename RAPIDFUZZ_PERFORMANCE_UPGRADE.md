# RapidFuzz Performance Upgrade

## Problem
Entity extraction was hanging for 2+ hours on articles with many entities due to slow fuzzy string matching in gazetteer fallback.

### Root Cause
- Using Python's `difflib.SequenceMatcher` for fuzzy matching
- When direct match fails, falls back to comparing against ALL gazetteer entries
- Example: 50 entities × 8,500 gazetteer entries = 425,000 comparisons
- `SequenceMatcher` is pure Python: ~1-2ms per comparison
- Total time: **425,000 × 1.5ms = 10.6 minutes minimum** (in practice 2+ hours)

### Article That Hung
- **Article ID**: `75845fdf-f1a7-4592-969f-8e7c41a4cf95`
- **Status**: Stuck for 2.5+ hours on entity extraction
- **Progress**: 7/200 articles completed before hanging

## Solution

### 1. Added `rapidfuzz` Library
**Performance**: 50-100x faster than `difflib.SequenceMatcher`
- C++ implementation vs pure Python
- ~0.01-0.05ms per comparison vs 1-2ms
- Same 425,000 comparisons: **~13 seconds** vs 10+ minutes

```python
# Before (slow)
from difflib import SequenceMatcher
score = SequenceMatcher(None, text1, text2).ratio()

# After (fast)
from rapidfuzz import fuzz
score = fuzz.ratio(text1, text2) / 100.0
```

### 2. Enhanced Logging
Added debug logging to track:
- Total entities vs gazetteer size
- Progress every 10 entities for large batches
- When expensive fallback fuzzy matching is used
- Match results for debugging

```python
logger.debug(f"🗺️  Matching {len(entities)} entities against {len(gazetteer_rows)} gazetteer entries")
logger.debug(f"🔍 Fuzzy matching '{entity_text}' against {len(candidates)} candidates")
logger.debug(f"✅ Fuzzy match: '{entity_text}' → '{match.name}' (score: 0.92)")
logger.debug(f"✅ Matched 45/50 entities (12 required fallback fuzzy matching)")
```

### 3. Safety Limit
Added gazetteer size check to prevent edge cases:
```python
if not match and index and len(gazetteer_rows) < 50000:
    # Only do fallback for reasonable-sized gazetteers
    # Prevents extreme cases (50k+ entries)
```

## Performance Comparison

| Scenario | SequenceMatcher | RapidFuzz | Speedup |
|----------|-----------------|-----------|---------|
| 50 entities × 8,500 gazetteer | 10-60 min | **13 seconds** | **46-277x** |
| 100 entities × 8,500 gazetteer | 20-120 min | **26 seconds** | **46-277x** |
| Direct match (no fallback) | Instant | Instant | Same |

## Implementation Details

### Files Changed
1. **requirements.txt**: Added `rapidfuzz>=3.0.0`
2. **src/pipeline/entity_extraction.py**:
   - Replaced `SequenceMatcher` with `rapidfuzz.fuzz.ratio()`
   - Re-enabled gazetteer fallback (now safe with rapidfuzz)
   - Added comprehensive debug logging
   - Added entity_text parameter to `_score_match()` for logging

### Code Changes

#### Updated `_score_match()`:
```python
def _score_match(
    norm_entity: str, candidates: Sequence[Gazetteer], entity_text: str = ""
) -> GazetteerMatch | None:
    """Score fuzzy matches with logging for large candidate sets."""
    if len(candidates) > 100 and entity_text:
        logger.debug(f"🔍 Fuzzy matching '{entity_text}' against {len(candidates)} candidates")
    
    for entry in candidates:
        # Use rapidfuzz (50-100x faster)
        score = fuzz.ratio(norm_entity, entry_norm) / 100.0
        if score >= 0.85:
            # Track best match
    
    if best_match and entity_text:
        logger.debug(f"✅ Fuzzy match: '{entity_text}' → '{best_match.name}' (score: {best_match.score:.2f})")
```

#### Updated `attach_gazetteer_matches()`:
```python
# Re-enabled fallback (now safe with rapidfuzz)
if not match and index and len(gazetteer_rows) < 50000:
    fallback_count += 1
    all_candidates = (candidate for candidates in index.values() for candidate in candidates)
    match = _score_match(norm, list(all_candidates), entity_text)

logger.debug(f"✅ Matched {matched_count}/{len(entities)} entities ({fallback_count} required fallback)")
```

## Expected Results

### Before
- **7 articles in 2.5+ hours** (hung on article #8)
- No visibility into matching process
- System appeared frozen

### After (with rapidfuzz)
- **200 articles in ~10-15 minutes**
- Debug logs show matching progress
- Clear indication when fallback matching is used
- Match quality scores visible in logs

## Testing Recommendations

1. **Monitor first run** with debug logging enabled
2. **Verify performance**: Should complete 200 articles in < 20 minutes
3. **Check match quality**: Review debug logs for match scores
4. **Resource usage**: Should stay under 3GB memory

## Deployment Steps

1. ✅ Update requirements.txt with rapidfuzz
2. ✅ Update entity_extraction.py with new code
3. ⏳ Commit and push changes
4. ⏳ Rebuild processor image
5. ⏳ Deploy to GKE
6. ⏳ Monitor logs for performance improvement

## Related Issues

- **Issue #8**: Article 75845fdf hung for 2.5+ hours
- **Root cause**: Expensive fuzzy matching with SequenceMatcher
- **Solution**: RapidFuzz + better logging
- **Status**: Code ready for deployment
