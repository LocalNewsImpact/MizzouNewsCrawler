# Telemetry SQLite Fallback Issue - Resolution

## Problem
Production containers were using SQLite for telemetry instead of PostgreSQL, causing errors:
```
Telemetry store missing discovery tables; recorded outcome without source audit: 
(sqlite3.OperationalError) no such table: sources
```

## Root Cause
The telemetry system (`src/telemetry/store.py`) determines its database URL through this fallback chain:
1. Check `TELEMETRY_DATABASE_URL` environment variable → **Not set**
2. Import `DATABASE_URL` from `src.config` → **Import succeeds** but exception handling was too broad
3. Fallback to SQLite (`sqlite:///data/mizzou.db`) → **This was happening in production**

The `src.config.DATABASE_URL` construction works correctly - it builds a PostgreSQL URL from individual environment variables:
- `DATABASE_ENGINE` = `postgresql+psycopg2`
- `DATABASE_HOST` = `127.0.0.1` (Cloud SQL Connector provides local proxy)
- `DATABASE_PORT` = `5432`
- `DATABASE_USER`, `DATABASE_PASSWORD`, `DATABASE_NAME` (from secrets)

## Why SQLite Was Being Used
The telemetry code had a silent `except Exception: pass` block that caught any import failures without logging. The import of `src.config.DATABASE_URL` might have been failing due to:
- Timing issues during container startup
- Missing dependencies during telemetry module initialization
- Circular import issues

## Failed Fix Attempts
### Attempt 1: Set `TELEMETRY_DATABASE_URL` with Variable Substitution
```yaml
- name: TELEMETRY_DATABASE_URL
  value: "postgresql+psycopg2://$(DATABASE_USER):$(DATABASE_PASSWORD)@127.0.0.1:5432/$(DATABASE_NAME)"
```
**Result**: Kubernetes expanded the variables correctly, but special characters in passwords weren't URL-encoded, causing:
```
sqlite3.OperationalError: near "ON": syntax error
```

This was reverted in commit `2edb044`.

## Implemented Fix (Commit b8e2413)
Added diagnostic logging and PostgreSQL validation to `src/telemetry/store.py`:

```python
def _determine_default_database_url() -> str:
    candidate = os.getenv("TELEMETRY_DATABASE_URL")
    if candidate:
        return candidate

    # Try to use the main application DATABASE_URL from config
    try:
        from src.config import DATABASE_URL as CONFIG_DATABASE_URL

        if CONFIG_DATABASE_URL:
            # Don't use SQLite in production - only accept postgresql URLs
            if CONFIG_DATABASE_URL.startswith("postgresql"):
                return CONFIG_DATABASE_URL
            logging.warning(
                f"Config DATABASE_URL is not PostgreSQL: {CONFIG_DATABASE_URL[:20]}... "
                f"Falling back to SQLite"
            )
    except Exception as e:
        logging.warning(
            f"Failed to import DATABASE_URL from config: {e}. "
            f"Falling back to SQLite"
        )

    return _SQLITE_FALLBACK_URL
```

### What This Fix Does
1. **Logs import failures**: We'll now see in logs WHY the import might be failing
2. **Validates PostgreSQL**: Only accepts PostgreSQL URLs from config
3. **Makes SQLite fallback explicit**: Warns when falling back to SQLite

### Expected Outcome
With the new logging, we'll either:
- **See telemetry use PostgreSQL** (no warnings logged) ✅
- **See specific error messages** explaining why config import failed, allowing us to fix the real issue

## Deployment Status
- **Code Fix**: Committed in `b8e2413`
- **Image Build**: Triggered `build-processor-manual` for commit `b8e2413`
- **Image Tag**: `processor:b8e2413` and `processor:v1.3.1`
- **Auto-Deploy**: Cloud Build will automatically update production deployment

## Verification Steps
Once the new processor image is deployed:

1. **Check processor logs** for telemetry warnings:
   ```bash
   kubectl logs -n production -l app=mizzou-processor --tail=100 | grep -i "telemetry\|sqlite"
   ```

2. **Run discovery job** and check for SQLite errors:
   ```bash
   kubectl logs -n production -l stage=discovery --tail=50 | grep -i "telemetry.*missing\|sqlite"
   ```

3. **Expected result**: No "missing discovery tables" errors, no SQLite warnings

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
