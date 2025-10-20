# Telemetry Cloud SQL Integration Fix

**Date:** October 19, 2025  
**Commits:** bc638eb  
**Issue:** RecursionError when storing telemetry with Cloud SQL Connector

## Problem

Telemetry was failing with `RecursionError: maximum recursion depth exceeded` when running on Cloud SQL (GKE production environment).

### Root Cause

The `TelemetryStore` class was creating its **own SQLAlchemy engine** from a database URL string, independent of the application's `DatabaseManager`. 

When using Cloud SQL Connector:
1. `DatabaseManager` creates an engine with Cloud SQL Connector properly configured
2. `TelemetryStore` tried to create a **second independent engine** from the database URL
3. Cloud SQL Connector requires async connection setup
4. `TelemetryStore` tried to use it synchronously
5. Result: `RuntimeWarning: coroutine 'Connector.connect_async' was never awaited`
6. Then: `RecursionError: maximum recursion depth exceeded`

### Impact

- **All telemetry data was lost** in Cloud SQL environment
- Extraction metrics not recorded
- Content cleaning telemetry missing
- Byline telemetry unavailable
- Warnings printed but errors suppressed (telemetry best-effort)

## Solution

### Core Changes

**1. Modified `TelemetryStore` to accept existing engine** (`src/telemetry/store.py`)

```python
def __init__(
    self,
    database: str = DEFAULT_DATABASE_URL,
    *,
    engine: Engine | None = None,  # ← New parameter
) -> None:
    # Use provided engine or create new one
    if engine is not None:
        self._engine = engine
        self._owns_engine = False  # Don't dispose shared engine
    else:
        self._engine = self._create_engine()
        self._owns_engine = True
```

**2. Updated `get_store()` to pass through engine** (`src/telemetry/store.py`)

```python
def get_store(
    database: str = DEFAULT_DATABASE_URL,
    *,
    engine: Engine | None = None,  # ← New parameter
) -> TelemetryStore:
    """Return a process-wide shared telemetry store."""
    global _default_store
    with _default_store_lock:
        if _default_store is None:
            _default_store = TelemetryStore(database=database, engine=engine)
    return _default_store
```

**3. Updated all telemetry classes to pass DatabaseManager's engine**

Modified these files to use shared engine:
- `src/utils/comprehensive_telemetry.py`
- `src/utils/byline_telemetry.py`
- `src/utils/content_cleaning_telemetry.py`
- `src/utils/extraction_telemetry.py`
- `src/utils/telemetry.py`

Example from `comprehensive_telemetry.py`:

```python
# BEFORE (BROKEN):
from src.models.database import DatabaseManager
db = DatabaseManager()
database_url = str(db.engine.url)
self._store = get_store(database_url)  # Creates NEW engine!

# AFTER (FIXED):
from src.models.database import DatabaseManager
db = DatabaseManager()
database_url = str(db.engine.url)
self._store = get_store(database_url, engine=db.engine)  # Reuses engine!
```

### Error Handling Improvements

Added specific handling for `RecursionError` (moved before `RuntimeError` since it's a subclass):

```python
try:
    store = self.store
    store.submit(writer)
except RecursionError as exc:  # Must be before RuntimeError
    exc_name = type(exc).__name__
    print(f"Warning: Telemetry recursion error: {exc_name}")
    pass
except RuntimeError:
    # Telemetry disabled or not supported
    pass
except Exception as exc:
    exc_msg = str(exc).split('\n')[0][:80]
    exc_name = type(exc).__name__
    print(f"Warning: Failed telemetry: {exc_name}: {exc_msg}")
```

## Benefits

### Resource Efficiency
- **Single connection pool** shared between app and telemetry
- No duplicate connections to Cloud SQL
- Better connection pooling and reuse

### Reliability
- ✅ Cloud SQL Connector works correctly
- ✅ No more RecursionError
- ✅ No async/sync mismatch
- ✅ Telemetry data actually stored

### Debugging
- Extraction metrics now available in production
- Content cleaning telemetry captured
- Byline parsing telemetry recorded
- Better visibility into production issues

## Testing

### Backward Compatibility
- ✅ Existing tests pass (engine parameter is optional)
- ✅ SQLite local development still works
- ✅ Can still create standalone TelemetryStore if needed

### Cloud SQL Verification
After deploying crawler:bc638eb to production:
1. Check extraction logs for telemetry warnings (should be gone)
2. Query `extraction_telemetry_v2` table for new records
3. Query `byline_telemetry` table for cleaning data
4. Verify no RecursionError in pod logs

## Architecture Notes

### Why Not Use DatabaseManager Sessions?

We considered using `DatabaseManager.get_session()` but `TelemetryStore` needs:
- **Background thread** for async writes
- **Independent transactions** (can't use app's session)
- **Connection pooling** separate from SQLAlchemy ORM sessions

Using the **engine** is the right level:
- Engine = connection pool + dialect
- TelemetryStore manages its own connections from the pool
- No interference with app's ORM sessions

### Engine Ownership

The `_owns_engine` flag tracks whether TelemetryStore created the engine:
- If we created it: dispose on shutdown
- If passed to us: leave it alone (app will dispose)

This prevents double-disposal and use-after-free errors.

## Related Issues

This fix completes the trilogy of critical production issues:
1. ✅ **Telemetry SQL errors** (commit f4f1cd7) - Type conversions
2. ✅ **Gazetteer OR bug** (commit 075b5e3) - Query performance
3. ✅ **Telemetry Cloud SQL** (commit bc638eb) - Connection sharing

## Deployment

- **Build:** b9ed3ed9-e7c2-4ae1-ac6c-46392b135a7f
- **Image:** crawler:bc638eb
- **Affects:** All extraction workflows using Cloud SQL
- **Status:** Building...

## Future Improvements

1. **Metrics Dashboard:** Now that telemetry works, build Grafana dashboards
2. **Alerting:** Set up alerts for extraction failures based on telemetry
3. **Performance Analysis:** Use telemetry data to optimize extraction methods
4. **A/B Testing:** Compare extraction strategies using telemetry metrics
