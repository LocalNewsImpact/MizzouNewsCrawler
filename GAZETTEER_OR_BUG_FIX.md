# Gazetteer OR Bug Fix - Critical Performance Issue

**Date:** October 19, 2025  
**Commit:** 075b5e3  
**Build:** 44919137  
**Impact:** CRITICAL - Entity extraction hanging indefinitely

## Problem

Entity extraction was hanging for 10-30 minutes per article, causing the extraction workflow to timeout and fail.

### Root Cause

**File:** `src/pipeline/entity_extraction.py`  
**Function:** `get_gazetteer_rows()`  
**Bug:** Lines 369-371 used **OR logic** instead of **AND logic** when multiple filters provided

```python
# BEFORE (BROKEN):
if len(filters) == 1:
    stmt = stmt.where(filters[0])
else:
    stmt = stmt.where(or_(*filters))  # ❌ BUG: OR instead of AND
```

When both `source_id` and `dataset_id` were provided, the query loaded:
- All gazetteer for this source (hundreds) **OR**
- All gazetteer for this dataset (**millions**)

This caused:
1. **Database query timeout** - Query tried to load millions of rows
2. **Memory exhaustion** - If query succeeded, millions of rows loaded into memory
3. **EntityRuler hang** - Creating patterns from millions of gazetteer entries
4. **Pattern application hang** - Applying millions of patterns to each document

### Why First Articles Succeeded

The entity extraction command **caches gazetteer by (source_id, dataset_id)**:

```python
# src/cli/commands/entity_extraction.py lines 136-152
gazetteer_cache: dict[tuple[str | None, str | None], list] = {}

for row in rows:
    cache_key = (source_id, dataset_id)
    if cache_key not in gazetteer_cache:
        gazetteer_cache[cache_key] = get_gazetteer_rows(...)  # ← OR bug hit here
    gazetteer_rows = gazetteer_cache[cache_key]
```

**Timeline:**
- **Article #1** (source A): Cache miss → Load gazetteer with OR bug → Hangs
- **Article #2** (source A): Cache hit → Uses cached gazetteer → Fast
- **Article #3** (source B): Cache miss → Load gazetteer with OR bug → Hangs
- **Article #4** (source B): Cache hit → Uses cached gazetteer → Fast

Each **first article from a new source** in a batch would hang.

## Solution

Changed to **AND logic** to load only gazetteer entries matching **BOTH** source AND dataset:

```python
# AFTER (FIXED):
# Use AND when multiple filters (need gazetteer for BOTH source AND dataset)
for filter_condition in filters:
    stmt = stmt.where(filter_condition)
```

This reduces gazetteer load from **millions to hundreds** of rows per source.

## Performance Impact

### Before Fix
- Article #1: 120s (hung on gazetteer load)
- Article #2: 30s (cache hit)
- Article #3: 120s (hung on new source)
- Article #4: **Infinite hang** (12+ minutes, never completed)

### After Fix
- Article #4: 30s ✅
- Article #5: 30s ✅
- Article #6: 30s ✅
- Article #7: 30s ✅
- Article #8: 30s ✅

**Result:** Consistent 30-second processing time per article, no hangs.

## Data Analysis

### Gazetteer Row Counts

For the stuck article's source:
- **Source-only query:** 563 rows (manageable)
- **Dataset-only query:** Timeout after 10 seconds (millions of rows)
- **Source AND Dataset (fixed):** 563 rows (correct)

The OR bug was loading the entire dataset gazetteer instead of just the source subset.

## Additional Changes

- Removed unused `from sqlalchemy import or_` import (line 18)
- Added comment explaining AND logic (line 365)

## Testing

Verified with new extraction workflow `mizzou-news-pipeline-1760918400`:
- ✅ Articles processing consistently in ~30 seconds
- ✅ No hangs or timeouts
- ✅ Entity extraction completing successfully
- ✅ Gazetteer matching working correctly

## Lessons Learned

1. **Cache hits hide bugs**: The bug only affected first article from each source
2. **OR vs AND matters**: Logical operators have huge performance implications
3. **Gazetteer size matters**: Dataset-level gazetteer can be millions of rows
4. **Multiple bottlenecks**: Bug caused issues in DB query, memory, and pattern matching

## Related Issues

- Telemetry SQL errors (fixed in f4f1cd7)
- Rapidfuzz performance (fixed in 0d8e219)
- CI/CD deployment reliability (fixed in 09f63d8)

## Deployment

- **Build:** 44919137-f3b0-458b-b108-87a17ac39552
- **Image:** processor:075b5e3
- **Revision:** 186
- **Status:** ✅ Successfully deployed and verified
