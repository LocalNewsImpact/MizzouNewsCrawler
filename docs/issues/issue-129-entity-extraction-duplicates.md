# Issue #129: Entity Extraction Duplicate Key Violations

## Problem Summary

Entity extraction batches were failing with PostgreSQL constraint violation errors when spaCy returned duplicate entities for the same article. The error occurred because duplicates like "CNN" and "cnn" both normalize to "cnn", violating the unique constraint `uq_article_entity` on columns `(article_id, entity_norm, entity_label, extractor_version)`.

### Error Example

```
sqlalchemy.exc.DatabaseError: (raised as a result of Query-invoked autoflush; consider using a session.no_autoflush block if this flush is occurring prematurely)
(pg8000.exceptions.DatabaseError) {'S': 'ERROR', 'V': 'ERROR', 'C': '23505', 'M': 'duplicate key value violates unique constraint "uq_article_entity"', 'D': 'Key (article_id, entity_norm, entity_label, extractor_version)=(2de39960-7c46-48ef-9d43-768f55bef831, cnn, ORG, spacy-en_core_web_sm-3.8.7) already exists.'}
```

### Impact

- Affected articles never persisted entities and remained in the backlog
- Processor pods continued looping on the same articles, wasting cycles
- Entity extraction stage could not fully catch up until duplicates were deduplicated

## Root Cause

The `save_article_entities()` function in `src/models/database.py` did not deduplicate entities before insertion. When spaCy's entity extractor returned the same entity with different casings (e.g., "CNN" and "cnn"), both would be processed through `_normalize_entity_text()` which converts them to the same normalized form ("cnn"). This created duplicate entries that violated the database's unique constraint.

## Solution

Added deduplication logic to `save_article_entities()` that:

1. **Tracks seen entities** during processing using a set of tuples: `(entity_norm, entity_label, extractor_version)`
2. **Skips duplicates** after normalization but before database insertion
3. **Preserves first occurrence** of each unique entity tuple
4. **Logs at DEBUG level** when duplicates are detected for debugging purposes
5. **Maintains existing behavior** including sentinel row logic and commit patterns

### Code Changes

**File:** `src/models/database.py`

```python
# Track seen entities to prevent duplicate key violations on unique
# constraint (article_id, entity_norm, entity_label, extractor_version).
# Since we're processing a single article_id, we only track the tuple
# (entity_norm, entity_label, extractor_version) within this function.
seen: set[tuple[str, str, str]] = set()

for entity in entities:
    # ... extract and normalize entity fields ...
    
    # Deduplicate within this article based on the unique constraint
    dedupe_key = (entity_norm, entity_label, entity_extractor_version)
    if dedupe_key in seen:
        logger.debug(
            "Skipping duplicate entity for article %s: "
            "norm=%s, label=%s, version=%s",
            article_id,
            entity_norm,
            entity_label,
            entity_extractor_version,
        )
        continue
    seen.add(dedupe_key)
```

## Testing

Comprehensive test coverage was added to validate the fix:

### Unit Tests (tests/models/test_database_manager.py)

1. **`test_save_article_entities_deduplicates_norm_label`**: Validates that duplicate entities (same normalized form and label) are deduplicated
2. **`test_save_article_entities_retains_distinct_labels`**: Ensures same text with different labels persists as separate entities
3. **`test_save_article_entities_handles_legacy_text_key`**: Tests mixed `entity_text`/`text` key formats with deduplication
4. **`test_save_article_entities_sentinel_when_all_duplicates`**: Verifies behavior when all entities collapse to a single unique entity

### Integration Tests (tests/test_parallel_processing_integration.py)

5. **`test_save_article_entities_deduplicates_with_autocommit_false`**: Tests the production scenario where `autocommit=False` is used in batch processing, ensuring duplicates don't cause constraint violations during commit

### Test Results

- ✅ All 5 save_article_entities tests pass
- ✅ All 37 entity extraction tests pass
- ✅ All 34 database manager tests pass
- ✅ Security scan: 0 issues found
- ✅ Linting: All checks pass

## Deployment

The fix is backwards-compatible and requires no schema changes or data migration.

### Deployment Steps

1. **Code deployment**: Deploy the updated processor image with the fix
2. **Verification**: Monitor processor logs for successful entity extraction without duplicate key errors
3. **Rollback plan**: If issues arise, rollback to previous processor image version

### Monitoring

After deployment, monitor:

- Entity extraction error rates (should decrease to zero for duplicate key violations)
- Entity extraction processing rate (should increase as backlog clears)
- Debug logs showing "Skipping duplicate entity" messages (expected for articles with duplicate entities)

## Related Files

- `src/models/database.py`: Core fix implementation
- `tests/models/test_database_manager.py`: Unit test coverage
- `tests/test_parallel_processing_integration.py`: Integration test coverage
- `src/cli/commands/entity_extraction.py`: Production usage with `autocommit=False`

## References

- **Issue**: #129
- **Unique Constraint**: `uq_article_entity` on `(article_id, entity_norm, entity_label, extractor_version)`
- **Model**: `ArticleEntity` in `src/models/__init__.py`
- **Normalization**: `_normalize_entity_text()` in `src/models/database.py`
