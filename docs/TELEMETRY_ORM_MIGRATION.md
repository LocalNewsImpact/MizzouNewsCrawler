# SQLAlchemy ORM Migration for Telemetry Tables

## Overview

This document outlines the approach for migrating complex telemetry tables (>20 columns) from raw SQL to SQLAlchemy ORM models to improve type safety and reduce schema drift errors.

## Motivation

Recent production issues highlighted risks with raw SQL INSERT statements on complex tables:

1. **Schema Drift**: Code CREATE TABLE statements diverged from Alembic migrations
2. **Column Count Mismatches**: INSERT statements missing columns (e.g., `created_at`)
3. **Constraint Violations**: SQLite vs PostgreSQL differences not caught in tests
4. **Maintenance Burden**: Large INSERT statements difficult to review and update

## Analysis of Telemetry Tables

Tables analyzed by column count from Alembic migrations:

| Table Name | Column Count | Recommendation |
|-----------|--------------|----------------|
| candidate_links | 35 | **ORM Recommended** |
| byline_cleaning_telemetry | 32 | **ORM Recommended** |
| extraction_telemetry_v2 | 27 | **ORM Recommended** |
| articles | 24 | **ORM Recommended** |
| url_verifications | 20 | Consider ORM |
| reviews | 19 | Raw SQL acceptable |
| background_processes | 17 | Raw SQL acceptable |

### Criteria for ORM Migration

**Strong recommendation (>20 columns):**
- High risk of column mismatches
- Complex INSERT statements difficult to maintain
- Frequent schema changes expected

**Consider ORM (15-20 columns):**
- Moderate complexity
- Evaluate based on change frequency
- May benefit from hybrid approach

**Raw SQL acceptable (<15 columns):**
- Simple enough for manual review
- Low change frequency
- Performance-critical paths

## Migration Strategy

### Phase 1: Create ORM Models (Completed)

Created `src/models/telemetry_orm.py` with models for:
- `BylineCleaningTelemetry` (32 columns)
- `ExtractionTelemetryV2` (27 columns)

### Phase 2: Gradual Migration

1. **Parallel Implementation**: Keep raw SQL working while adding ORM option
2. **Feature Flag**: Use environment variable to toggle ORM usage
3. **Testing**: Run both implementations in parallel during migration
4. **Validation**: Compare outputs to ensure equivalence

### Phase 3: Adoption

1. Enable ORM for new code first
2. Migrate high-traffic paths
3. Migrate remaining usages
4. Remove raw SQL implementations

### Phase 4: Schema Evolution

Once ORM is primary:
1. Use Alembic to generate migrations from model changes
2. Automatic detection of schema drift
3. Type-safe refactoring

## Implementation Example

### Before (Raw SQL - Error Prone)

```python
def save_telemetry(self, session):
    with self.store.connection() as conn:
        conn.execute(
            """
            INSERT INTO byline_cleaning_telemetry (
                id, article_id, candidate_link_id, source_id,
                source_name, raw_byline, raw_byline_length,
                raw_byline_words, extraction_timestamp,
                cleaning_method, source_canonical_name,
                final_authors_json, final_authors_count,
                final_authors_display, confidence_score,
                processing_time_ms, has_wire_service,
                has_email, has_title, has_organization,
                source_name_removed, duplicates_removed_count,
                likely_valid_authors, likely_noise,
                requires_manual_review, cleaning_errors,
                parsing_warnings, created_at  # <- Easy to forget!
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 
                     ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session["telemetry_id"],
                session.get("article_id"),
                session.get("candidate_link_id"),
                # ... 25 more parameters - easy to mismatch order!
                datetime.utcnow(),
            ),
        )
```

### After (ORM - Type Safe)

```python
from src.models.telemetry_orm import BylineCleaningTelemetry
from sqlalchemy.orm import Session

def save_telemetry(self, session_data):
    telemetry = BylineCleaningTelemetry(
        id=session_data["telemetry_id"],
        article_id=session_data.get("article_id"),
        candidate_link_id=session_data.get("candidate_link_id"),
        source_id=session_data.get("source_id"),
        source_name=session_data.get("source_name"),
        raw_byline=session_data["raw_byline"],
        raw_byline_length=session_data["raw_byline_length"],
        raw_byline_words=session_data["raw_byline_words"],
        extraction_timestamp=session_data["extraction_timestamp"],
        cleaning_method=session_data.get("cleaning_method"),
        source_canonical_name=session_data.get("source_canonical_name"),
        final_authors_json=session_data.get("final_authors_json"),
        final_authors_count=session_data.get("final_authors_count"),
        final_authors_display=session_data.get("final_authors_display"),
        confidence_score=session_data["confidence_score"],
        processing_time_ms=session_data.get("processing_time_ms"),
        has_wire_service=session_data["has_wire_service"],
        has_email=session_data["has_email"],
        has_title=session_data["has_title"],
        has_organization=session_data["has_organization"],
        source_name_removed=session_data["source_name_removed"],
        duplicates_removed_count=session_data["duplicates_removed_count"],
        likely_valid_authors=session_data.get("likely_valid_authors"),
        likely_noise=session_data.get("likely_noise"),
        requires_manual_review=session_data.get("requires_manual_review"),
        cleaning_errors=session_data.get("cleaning_errors"),
        parsing_warnings=session_data.get("parsing_warnings"),
        created_at=datetime.utcnow(),  # Type checker ensures this is datetime!
    )
    
    session = Session(self.store.engine)
    session.add(telemetry)
    session.commit()
```

### Benefits Demonstrated

1. **Type Safety**: IDE and type checkers validate types
2. **Autocomplete**: IDE suggests available attributes
3. **Refactoring**: Easy to find all usages of a column
4. **Schema Validation**: SQLAlchemy validates against database schema
5. **Missing Columns**: Compiler errors if required columns missing

## Testing Strategy

### Unit Tests with ORM

```python
def test_byline_telemetry_orm(tmp_path):
    from src.models.telemetry_orm import BylineCleaningTelemetry, Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    
    # Create test database
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    
    # Create telemetry record
    telemetry = BylineCleaningTelemetry(
        id="test-123",
        raw_byline="By John Doe",
        extraction_timestamp=datetime.utcnow(),
        confidence_score=0.9,
        created_at=datetime.utcnow()
    )
    
    # Save
    session = Session(engine)
    session.add(telemetry)
    session.commit()
    
    # Query
    result = session.query(BylineCleaningTelemetry).filter_by(id="test-123").first()
    assert result.raw_byline == "By John Doe"
    assert result.confidence_score == 0.9
```

### Integration Tests with PostgreSQL

The ORM models work seamlessly with PostgreSQL in CI:

```yaml
- name: Run PostgreSQL integration tests
  env:
    DATABASE_URL: "postgresql://postgres:postgres@localhost:5432/mizzou_test"
  run: |
    pytest -v tests/test_telemetry_orm.py
```

## Performance Considerations

### ORM Overhead

- **Typical overhead**: 10-20% compared to raw SQL
- **Acceptable for**: Batch inserts, background jobs, telemetry
- **Not recommended for**: Hot paths with microsecond requirements

### Optimization Techniques

1. **Bulk Operations**: Use `session.bulk_insert_mappings()` for batch inserts
2. **Connection Pooling**: Configure pool size appropriately
3. **Query Optimization**: Use `.options()` for eager loading
4. **Hybrid Approach**: Keep raw SQL for performance-critical paths

Example bulk insert:

```python
records = [
    {"id": "1", "raw_byline": "By Alice", ...},
    {"id": "2", "raw_byline": "By Bob", ...},
]
session.bulk_insert_mappings(BylineCleaningTelemetry, records)
session.commit()
```

## Migration Checklist

For each table being migrated:

- [ ] Create ORM model in `src/models/telemetry_orm.py`
- [ ] Add unit tests for model
- [ ] Add integration tests with PostgreSQL
- [ ] Update existing code to use ORM (with feature flag)
- [ ] Run parallel implementation in staging
- [ ] Monitor performance metrics
- [ ] Switch production to ORM
- [ ] Remove raw SQL code path
- [ ] Update documentation

## Next Steps

1. **Immediate**: Use ORM models in new code
2. **Short-term**: Migrate `byline_cleaning_telemetry` writes to ORM
3. **Medium-term**: Migrate `extraction_telemetry_v2` to ORM
4. **Long-term**: Evaluate remaining tables (articles, candidate_links)

## References

- SQLAlchemy ORM Tutorial: https://docs.sqlalchemy.org/en/20/orm/tutorial.html
- Alembic Autogenerate: https://alembic.sqlalchemy.org/en/latest/autogenerate.html
- Schema Validation Script: `scripts/validate_telemetry_schemas.py`
