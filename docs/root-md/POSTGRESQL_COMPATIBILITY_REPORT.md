# PostgreSQL Compatibility Report

Generated: 2025-11-02

## Summary

This report identifies all SQLite-specific code patterns found in the production codebase and assesses their PostgreSQL compatibility risk.

## Found Issues

### 🔴 HIGH PRIORITY - Needs Immediate Fix

These will fail in PostgreSQL production environment:

1. **`src/utils/comprehensive_telemetry.py`**
   - Lines: 650, 680
   - Pattern: `datetime('now')`
   - Fix Required: Convert to `CURRENT_TIMESTAMP` or Python datetime
   - Risk: HIGH - Used in production telemetry queries

2. **`src/services/url_verification_service.py`**
   - Line: 294
   - Pattern: `datetime('now', '-1 minute')`
   - Fix Required: Use Python timedelta or PostgreSQL `NOW() - INTERVAL '1 minute'`
   - Risk: HIGH - Used in verification queries

### 🟡 MEDIUM PRIORITY - Needs Review

These use dialect detection or are SQLite-specific contexts:

3. **`src/models/database.py`**
   - Lines: 1449, 1452
   - Pattern: `INSERT OR IGNORE`
   - Status: ✅ SAFE - Uses `if "sqlite" in engine.dialect.name:` check
   - Risk: LOW - Properly gated by dialect detection

4. **`src/models/database.py`**
   - Lines: 213-216, 1226, 1228, 1553
   - Pattern: `PRAGMA` statements
   - Status: ⚠️ REVIEW NEEDED
   - Lines 213-216: In `set_sqlite_pragma()` function - should only run for SQLite
   - Lines 1226, 1228, 1553: `PRAGMA table_info` - needs dialect check
   - Risk: MEDIUM - May fail if called on PostgreSQL connections

5. **`src/telemetry/store.py`**
   - Lines: 275-278
   - Pattern: `PRAGMA` statements
   - Status: ⚠️ REVIEW NEEDED - In `_configure_sqlite_engine()` but needs verification
   - Risk: MEDIUM

6. **`src/telemetry/store.py`**
   - Lines: 536-537
   - Pattern: `AUTOINCREMENT` string replacement
   - Status: ✅ LIKELY SAFE - Appears to be handling schema translation
   - Risk: LOW

7. **`src/utils/comprehensive_telemetry.py`**
   - Line: 473
   - Pattern: `PRAGMA table_info`
   - Status: ⚠️ REVIEW NEEDED - Needs PostgreSQL equivalent query
   - Risk: MEDIUM

## Recommended Actions

### Immediate (Before Next Deploy)

1. Fix `src/utils/comprehensive_telemetry.py` datetime queries
2. Fix `src/services/url_verification_service.py` datetime query
3. Add dialect checks to all `PRAGMA table_info` usage

### Short Term

1. Audit all `PRAGMA` usage to ensure dialect gates
2. Add integration tests for telemetry queries against PostgreSQL
3. Create helper functions for cross-database datetime operations

### Long Term

1. Eliminate all raw SQL datetime functions - use Python exclusively
2. Create abstraction layer for schema introspection (handles PRAGMA vs pg_catalog)
3. Add pre-commit hook running the SQLite pattern detection test

## Test Coverage

New test added: `tests/test_telemetry_postgresql_compatibility.py::test_no_sqlite_patterns_in_production_code`

Run locally before every commit:
```bash
pytest tests/test_telemetry_postgresql_compatibility.py -xvs
```

## Risk Assessment

- **Critical Risk**: 2 files (datetime queries in active production code)
- **Medium Risk**: 3 files (PRAGMA usage needing verification)
- **Low Risk**: 2 files (properly gated or safe transformations)

**Estimated Fix Time**: 2-4 hours to fix HIGH priority items
