# Telemetry Database Resolution Fix (PR #136)

## Overview

This document describes the fix implemented in PR #136 to resolve issues with telemetry database resolution in the `NewsDiscovery` service. The fix ensures that telemetry data is properly persisted to the production Cloud SQL database instead of falling back to a local SQLite database.

## Problem Statement

Prior to this fix, the `NewsDiscovery` class had a hardcoded default database URL of `"sqlite:///data/mizzou.db"` for its `database_url` parameter. This caused two issues:

1. **Production Data Loss**: In production environments with Cloud SQL configured, telemetry data was being written to a local SQLite file instead of the Cloud SQL database.

2. **Inconsistent Database Usage**: The main discovery operations used Cloud SQL (via `DATABASE_URL` configuration), but the telemetry system defaulted to SQLite, creating a split-brain scenario.

## Solution

The fix implements a flexible database URL resolution mechanism that:

1. **Respects Explicit Configuration**: When an explicit `database_url` is provided, it is used as-is.

2. **Falls Back to Configured Database**: When no explicit `database_url` is provided, it resolves to the configured `DATABASE_URL` from `src.config`.

3. **Provides Safe Defaults**: If no configuration is available, it safely falls back to SQLite for development/testing.

4. **Enables Telemetry Cloud SQL Usage**: Crucially, when no explicit database URL is provided, telemetry receives `None`, allowing it to use the `DatabaseManager`'s Cloud SQL connection.

## Implementation Details

### Changes Made

#### 1. `NewsDiscovery.__init__()` Signature Change

**Before:**
```python
def __init__(
    self,
    database_url: str = "sqlite:///data/mizzou.db",
    ...
):
```

**After:**
```python
def __init__(
    self,
    database_url: str | None = None,
    ...
):
```

#### 2. Database URL Resolution Method

Added a new static method `_resolve_database_url()`:

```python
@staticmethod
def _resolve_database_url(candidate: str | None) -> str:
    if candidate:
        return candidate

    try:
        from src.config import DATABASE_URL as configured_database_url
        return configured_database_url or "sqlite:///data/mizzou.db"
    except Exception:
        return "sqlite:///data/mizzou.db"
```

This method:
- Returns the explicit URL if provided
- Falls back to `DATABASE_URL` from config
- Handles import errors gracefully
- Provides SQLite as final fallback

#### 3. Telemetry Initialization Fix

**Before:**
```python
self.telemetry = create_telemetry_system(
    database_url=self.database_url,
)
```

**After:**
```python
telemetry_database_url = resolved_database_url if database_url else None
self.telemetry = create_telemetry_system(
    database_url=telemetry_database_url,
)
```

**Key Insight**: When `database_url` parameter is `None` (not explicitly provided), telemetry receives `None`, allowing `create_telemetry_system()` to use `DatabaseManager()` which connects to Cloud SQL in production.

#### 4. `run_discovery_pipeline()` Update

Updated the function signature to accept `database_url: str | None = None` instead of `database_url: str = "sqlite:///data/mizzou.db"`, maintaining consistency with the class constructor.

## Behavior Scenarios

### Production Scenario (Cloud SQL)

**Environment:**
- `DATABASE_URL` = `"postgresql+psycopg2://user:pass@/dbname?host=/cloudsql/instance"`
- `USE_CLOUD_SQL_CONNECTOR` = `true`

**Code:**
```python
discovery = NewsDiscovery()  # No explicit database_url
```

**Result:**
- `discovery.database_url` = Cloud SQL URL from config
- `telemetry` receives `None`, uses `DatabaseManager`'s Cloud SQL connection
- Both discovery and telemetry write to the same Cloud SQL database ✅

### Development Scenario (SQLite)

**Environment:**
- No `DATABASE_URL` configured
- Local development environment

**Code:**
```python
discovery = NewsDiscovery()  # No explicit database_url
```

**Result:**
- `discovery.database_url` = `"sqlite:///data/mizzou.db"` (fallback)
- `telemetry` receives `None`, uses `DatabaseManager` which also falls back to SQLite
- Both discovery and telemetry write to SQLite ✅

### Explicit Override Scenario

**Environment:**
- Any environment

**Code:**
```python
discovery = NewsDiscovery(database_url="postgresql://test:test@localhost:5432/testdb")
```

**Result:**
- `discovery.database_url` = Explicit URL provided
- `telemetry` receives the same explicit URL
- Both use the specified database ✅

## Testing

Comprehensive test coverage was added in `tests/test_telemetry_database_resolution.py`:

### Test Categories

1. **URL Resolution Tests** (`TestResolveDatabaseUrl`)
   - Test explicit URL handling
   - Test config fallback behavior
   - Test SQLite fallback
   - Test exception handling

2. **Initialization Tests** (`TestNewsDiscoveryInitialization`)
   - Test with explicit database_url
   - Test without database_url (config resolution)
   - Test SQLite fallback

3. **Telemetry Integration Tests** (`TestTelemetryDatabaseUrlPassing`)
   - Verify telemetry receives correct URL
   - Verify telemetry receives `None` when appropriate

4. **Function Signature Tests** (`TestRunDiscoveryPipelineSignature`)
   - Verify `run_discovery_pipeline()` signature
   - Verify parameter passing

5. **Scenario Tests** (`TestDatabaseUrlBehaviorIntegration`)
   - Production Cloud SQL scenario
   - Development SQLite scenario
   - Explicit override scenario

### Running Tests

```bash
# Run telemetry database resolution tests
pytest tests/test_telemetry_database_resolution.py -v

# Run all discovery tests
pytest tests/crawler/test_discovery*.py tests/integration/test_discovery*.py -v
```

## Migration Guide

### For Existing Code

**Before (Old Code):**
```python
# Explicit SQLite URL (still works)
discovery = NewsDiscovery(database_url="sqlite:///data/mizzou.db")

# Used hardcoded SQLite default
discovery = NewsDiscovery()
```

**After (Updated Code):**
```python
# Explicit URL (works same as before)
discovery = NewsDiscovery(database_url="sqlite:///data/mizzou.db")

# Uses configured DATABASE_URL or SQLite fallback
discovery = NewsDiscovery()  # Recommended for production

# Can still explicitly specify Cloud SQL
discovery = NewsDiscovery(database_url=os.getenv("DATABASE_URL"))
```

### Breaking Changes

**None** - This is a backward-compatible change:
- Existing code with explicit `database_url` works unchanged
- Existing code without `database_url` gets better behavior (uses configured database)

### Deployment Considerations

1. **No Code Changes Required**: Existing deployments will automatically benefit from the fix.

2. **Environment Variables**: Ensure `DATABASE_URL` is properly configured in production:
   ```bash
   DATABASE_URL=postgresql+psycopg2://user:pass@/dbname?host=/cloudsql/instance
   USE_CLOUD_SQL_CONNECTOR=true
   ```

3. **Telemetry Tables**: Ensure telemetry tables exist in Cloud SQL database:
   ```bash
   # Run Alembic migrations
   alembic upgrade head
   ```

4. **Verification**: After deployment, verify telemetry data appears in Cloud SQL:
   ```sql
   SELECT COUNT(*) FROM operations WHERE operation_type = 'crawl_discovery';
   SELECT COUNT(*) FROM discovery_http_status_tracking;
   SELECT COUNT(*) FROM discovery_method_effectiveness;
   ```

## Rollback Plan

If issues arise, rollback is simple:

1. **Revert the commit** from PR #136
2. **Redeploy** the previous version
3. **Note**: Any telemetry data written to Cloud SQL during the deployment will remain there (no data loss)

## Benefits

1. ✅ **Unified Database Usage**: Both discovery and telemetry use the same database
2. ✅ **Production Data Persistence**: Telemetry data is properly persisted in Cloud SQL
3. ✅ **Backward Compatible**: Existing code continues to work
4. ✅ **Flexible Configuration**: Supports explicit overrides for testing
5. ✅ **Fail-Safe**: Graceful fallback to SQLite in development

## Related Documentation

- [Telemetry System Documentation](./telemetry.md)
- [Database Configuration](../README.md#database-configuration)
- [Cloud SQL Setup](../docs/cloud-sql-setup.md)

## Authors

- Initial fix: @dkiesow
- Test coverage and documentation: @github-copilot

## References

- PR #136: Fix telemetry default database resolution
- Issue: Telemetry data not persisting in production Cloud SQL
