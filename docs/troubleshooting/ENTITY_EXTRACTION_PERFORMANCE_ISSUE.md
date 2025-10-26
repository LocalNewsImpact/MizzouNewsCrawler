# Entity Extraction Performance Issue

**Date**: October 15, 2025 18:04 UTC  
**Status**: CRITICAL - Entity extraction is 60x slower than expected

## Problem Summary

The processor pod is stuck in an infinite loop processing the same 13 articles because:

1. ✅ Query finds 13 articles without entities
2. ❌ Entity extraction subprocess runs for 20+ minutes on 13 small articles (58K chars total)
3. ❌ Process never completes, never commits to database
4. ❌ Next cycle: same 13 articles found (no entities added)
5. 🔁 REPEAT FOREVER

## Performance Analysis

### Expected Performance
- 13 articles, ~4,500 chars average
- Total: 58,308 characters
- spaCy en_core_web_sm: ~10,000 chars/second
- **Expected time**: ~6 seconds

### Actual Performance  
- **Actual time**: 20+ minutes (1200+ seconds)
- **Performance**: ~48 chars/second
- **Slowdown**: **208x slower than expected!**

### Resource Usage
```
PID 12: extract-entities subprocess
- CPU: 79% (nearly maxed)
- Memory: 1980MB  
- CPU time: 15:32 minutes
- Status: Running (not hung)
```

## Root Causes (Hypotheses)

### 1. Database Connection Issue (LIKELY)
The entity extraction fetches gazetteer data for EVERY article:

```python
for row in rows:  # 13 articles
    # Get gazetteer rows for THIS source
    gazetteer_rows = get_gazetteer_rows(session, source_id, dataset_id)
    
    entities = extractor.extract(text, gazetteer_rows=gazetteer_rows)
    entities = attach_gazetteer_matches(session, source_id, dataset_id, entities, gazetteer_rows)
```

If `get_gazetteer_rows()` or `attach_gazetteer_matches()` are slow (N+1 queries, missing indexes, etc.), this would compound 13x.

### 2. spaCy Model Issue
- Model might be loading for EACH article instead of once
- Or model is slower in container environment
- Or missing optimizations (no GPU, threading issues)

### 3. Gazetteer Matching Overhead
The code matches entities against gazetteer entries. If gazetteer table is large and not indexed properly, this could be very slow.

## Diagnosis Steps

### 1. Check get_gazetteer_rows performance
```python
# In src/pipeline/entity_extraction.py
import time

def get_gazetteer_rows(...):
    start = time.time()
    # ... existing code ...
    elapsed = time.time() - start
    if elapsed > 0.1:
        logger.warning(f"get_gazetteer_rows took {elapsed:.2f}s")
```

### 2. Check if gazetteer is fetched once or per-article
Add logging to see if it's being called 13 times or 1 time.

### 3. Profile spaCy extraction
```python
start = time.time()
entities = extractor.extract(text, gazetteer_rows=gazetteer_rows)
elapsed = time.time() - start
if elapsed > 1.0:
    logger.warning(f"spaCy extraction took {elapsed:.2f}s for {len(text)} chars")
```

## Immediate Workarounds

### Option 1: Disable Entity Extraction Temporarily
```yaml
# k8s/processor-deployment.yaml
env:
  - name: ENABLE_ENTITY_EXTRACTION
    value: "false"  # Disable until fixed
```

This lets cleaning and ML analysis proceed without blocking on slow entity extraction.

### Option 2: Reduce Batch Size
```yaml
env:
  - name: GAZETTEER_BATCH_SIZE
    value: "1"  # Process 1 article at a time
```

This won't fix the performance but will prevent 13-article timeouts.

### Option 3: Increase Timeout
Add a timeout to the subprocess call in continuous_processor.py:
```python
proc = subprocess.Popen(..., timeout=300)  # 5 min timeout
```

After timeout, kill and retry with smaller batch.

## Long-term Solutions

### 1. Optimize Gazetteer Queries
- Add indexes on gazetteer lookups
- Cache gazetteer rows per source (not per article)
- Batch gazetteer matching

### 2. Profile and Optimize spaCy
- Check if model is being reloaded
- Use spaCy's `nlp.pipe()` for batch processing
- Consider using smaller model or disabling unused components

### 3. Move Entity Extraction to Async Job
Like we did with extraction, move entity extraction to separate jobs:
- `k8s/entity-extraction-job.yaml`
- Run on schedule, not in continuous loop
- Can tune resources specifically for entity extraction

## Recommendation

**IMMEDIATE**: Disable entity extraction in processor:

```yaml
# k8s/processor-deployment.yaml
- name: ENABLE_ENTITY_EXTRACTION
  value: "false"
```

Then proceed with Phase 2 testing. Entity extraction can be fixed separately.

**NEXT**: Add detailed logging to identify the bottleneck (gazetteer vs spaCy vs database).

**FUTURE**: Consider moving entity extraction to dedicated jobs like extraction.
