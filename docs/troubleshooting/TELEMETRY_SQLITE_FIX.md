# Telemetry PostgreSQL Requirement - FINAL FIX

## Problem History
Production containers were incorrectly using SQLite for telemetry instead of PostgreSQL, causing errors:
```
Telemetry store missing discovery tables; recorded outcome without source audit: 
(sqlite3.OperationalError) no such table: sources
```

This issue persisted across multiple attempts to fix it because the telemetry system had a **silent SQLite fallback** that would activate whenever PostgreSQL configuration failed.

## Root Cause
The telemetry system (`src/telemetry/store.py`) had a dangerous fallback chain:
1. Check `TELEMETRY_DATABASE_URL` environment variable → **Not set in Kubernetes**
2. Try to import `DATABASE_URL` from `src.config` → **Could fail due to timing/initialization**
3. **Silently fallback to SQLite** → **This was the bug**

The SQLite fallback was logged at DEBUG level, making it invisible in production logs.

## Why SQLite Fallback Is Wrong
1. **Production uses PostgreSQL** (Cloud SQL with pg8000 driver)
2. **Local development uses PostgreSQL** (localhost:5432)
3. **CI uses PostgreSQL** (postgres-integration job)
4. **SQLite compatibility issues** caused multiple production failures:
   - PRAGMA statements fail on PostgreSQL
   - INSERT OR IGNORE syntax fails on PostgreSQL
   - Aggregate functions return different types (strings vs integers)
   - Row access patterns differ between SQLite and PostgreSQL

## FINAL FIX (Commits c538da0, ee2ca86, and current)

### Three-Part Solution:

#### 1. Set TELEMETRY_DATABASE_URL in Kubernetes (Commit c538da0)
Added explicit `TELEMETRY_DATABASE_URL` to all Kubernetes deployments:

```yaml
# k8s/argo/base-pipeline-workflow.yaml (all 3 steps)
# k8s/processor-deployment.yaml
- name: TELEMETRY_DATABASE_URL
  value: "$(DATABASE_ENGINE)://$(DATABASE_USER):$(DATABASE_PASSWORD)@$(DATABASE_HOST):$(DATABASE_PORT)/$(DATABASE_NAME)"
```

This uses the same template as `DATABASE_URL`, ensuring telemetry gets PostgreSQL connection info.

#### 2. Improve Fallback Warning Visibility (Commit ee2ca86)
Changed fallback logging from DEBUG to WARNING level to make SQLite fallback visible in production logs.

#### 3. Remove SQLite Fallback Entirely (Current Commit)
**Completely removed SQLite fallback** from `src/telemetry/store.py`:
- Removed `_SQLITE_FALLBACK_URL` constant
- Changed `_determine_default_database_url()` to **FAIL LOUDLY** if PostgreSQL URL not found
- Added comprehensive validation that rejects non-PostgreSQL URLs
- Added informative error messages pointing to `TELEMETRY_DATABASE_URL`

```python
def _determine_default_database_url() -> str:
    """Determine the PostgreSQL database URL for telemetry.
    
    IMPORTANT: Telemetry MUST use PostgreSQL, never SQLite.
    If this function fails to find a database URL, it will raise an error
    rather than silently falling back to SQLite.
    """
    # Check TELEMETRY_DATABASE_URL first (set in Kubernetes)
    candidate = os.getenv("TELEMETRY_DATABASE_URL")
    if candidate:
        if not candidate.startswith("postgresql"):
            raise ValueError("TELEMETRY_DATABASE_URL must be PostgreSQL")
        return candidate
    
    # Try config import...
    # If all fails: RAISE ERROR instead of falling back to SQLite
    raise RuntimeError(
        "No PostgreSQL database URL found for telemetry. "
        "Set TELEMETRY_DATABASE_URL environment variable."
    )
```

### What This Achieves
1. ✅ **Production**: `TELEMETRY_DATABASE_URL` explicitly set → PostgreSQL always used
2. ✅ **Local Development**: Uses PostgreSQL from `src.config` or fails loudly
3. ✅ **CI**: Uses `TEST_DATABASE_URL` (PostgreSQL) or fails
4. ✅ **No Silent Failures**: Missing config causes startup failure, not runtime SQLite errors
5. ✅ **No Compatibility Issues**: SQLite code paths can never execute

### Deployment
These changes require:
1. **Kubernetes configs** already deployed with `TELEMETRY_DATABASE_URL`
2. **Code deployment** with SQLite fallback removed
3. **No backward compatibility** - old code with SQLite fallback will continue to cause issues

### Verification
After deployment, telemetry will either:
- ✅ **Work correctly** using PostgreSQL
- ❌ **Fail at startup** with clear error message about missing `TELEMETRY_DATABASE_URL`

**No more silent SQLite fallback causing runtime failures.**

## Alternative Solutions (If Logging Shows Import Still Fails)
If the logging reveals that `src.config.DATABASE_URL` import consistently fails:

### Option 1: Set DATABASE_URL Explicitly
Add to deployment manifests (but need URL encoding for passwords):
```yaml
- name: DATABASE_URL
  value: "postgresql+psycopg2://$(DATABASE_USER):$(DATABASE_PASSWORD)@127.0.0.1:5432/$(DATABASE_NAME)"
```

### Option 2: Use Templating for URL Construction
Use a ConfigMap or init container to construct the URL with proper URL encoding.

### Option 3: Modify Telemetry to Build URL Directly
Change `src/telemetry/store.py` to construct the URL from individual env vars (like `src.config` does) instead of importing it.

## Files Modified
- `src/telemetry/store.py` - Added logging and PostgreSQL validation
- ~~`k8s/processor-deployment.yaml`~~ - No changes needed (reverted)
- ~~`k8s/argo/base-pipeline-workflow.yaml`~~ - No changes needed (reverted)

## Next Steps
1. Wait for Cloud Build to complete (build ID: `12405a0b-a15b-4ad2-a62f-4803dd73ca61`)
2. Wait for processor pod to restart with new image
3. Check logs for telemetry warnings
4. Test with discovery job
5. If still using SQLite, implement one of the alternative solutions based on log insights
