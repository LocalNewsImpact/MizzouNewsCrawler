# BigQuery Export Database Configuration Fixes

**Date:** October 17, 2025  
**Branch:** feature/gcp-kubernetes-deployment  
**Commit:** 56fa1cb

## Problem Summary

The BigQuery export functionality was failing silently because:

1. **Missing library import**: The `google-cloud-bigquery` library import was failing in the CLI command loading, causing the `bigquery-export` command to not be registered
2. **Telemetry SQLite warnings**: The telemetry module was not properly detecting Cloud SQL configuration and falling back to SQLite with annoying warnings

## Root Cause Analysis

### Issue 1: Silent Import Failure

The dynamic CLI command loading in `src/cli/cli_modular.py` catches import errors but only logs warnings (which aren't visible in pod logs). When the `bigquery_export` command module tried to import:

```python
from google.cloud import bigquery
```

It failed because either:
- The library wasn't installed (unlikely - it's in requirements-processor.txt)
- OR the image was built before the library was added
- OR there was a build cache issue

The CLI's exception handler caught this and just logged a warning that we never saw:

```python
except (ImportError, ModuleNotFoundError) as e:
    logger.warning(f"Failed to load command '{command}': {e}")
    return None
```

This caused the command to silently not exist when running in the pod.

### Issue 2: Telemetry Database Configuration

The `src/telemetry/store.py` module was checking if `config.DATABASE_URL` started with "postgresql", but when using Cloud SQL Connector:

1. The environment only provides `DATABASE_USER`, `DATABASE_PASSWORD`, `DATABASE_NAME` (individual components)
2. The config module defaults `DATABASE_URL` to `"sqlite:///data/mizzou.db"` when it can't build a full URL
3. The telemetry module saw this SQLite URL and logged a warning on every import

## Fixes Implemented

### Fix 1: Telemetry Database URL Construction

Modified `src/telemetry/store.py` `_determine_default_database_url()` to:

1. **Detect Cloud SQL Connector mode**: Check if `USE_CLOUD_SQL_CONNECTOR=true` and `CLOUD_SQL_INSTANCE` is set
2. **Build PostgreSQL URL**: Construct URL from individual env vars:
   ```python
   if USE_CLOUD_SQL_CONNECTOR and CLOUD_SQL_INSTANCE and DATABASE_USER and DATABASE_NAME:
       db_url = f"postgresql://{user}:{password}@/{DATABASE_NAME}"
       return db_url
   ```
3. **Fallback logic**: Try `DATABASE_HOST`-based URL construction if not using connector
4. **Debug logging**: Changed warning to debug level when genuinely falling back to SQLite

**Result**: Eliminates the "Falling back to SQLite" warnings in production

### Fix 2: Processor Image Rebuild

Triggered a fresh build of the processor image (build ID: 17a0fbca) to ensure:

1. Latest code with telemetry fix is included
2. `google-cloud-bigquery[pandas]>=3.13.0` is properly installed
3. All dependencies are fresh (no cache issues)

## Verification Plan

Created `scripts/test-bigquery-export.sh` to verify:

1. ✅ google-cloud-bigquery library is installed
2. ✅ bigquery_export module can be imported
3. ✅ CLI command `bigquery-export` is registered and shows help
4. ✅ No SQLite fallback warnings appear with Cloud SQL config

## Next Steps

1. **Wait for build to complete** (build 17a0fbca)
2. **Run test script**: `./scripts/test-bigquery-export.sh`
3. **Verify all tests pass**: Particularly that the command is now available
4. **Test actual export**: Create a test job and verify it exports data to BigQuery
5. **Monitor CronJob**: Ensure the daily export runs successfully

## Related Files

- `src/telemetry/store.py` - Fixed database URL detection
- `src/pipeline/bigquery_export.py` - Export logic (unchanged)
- `src/cli/commands/bigquery_export.py` - CLI command (unchanged)
- `src/cli/cli_modular.py` - Dynamic command loading (unchanged)
- `requirements-processor.txt` - Contains google-cloud-bigquery dependency
- `k8s/bigquery-export-cronjob.yaml` - CronJob manifest (unchanged)
- `scripts/test-bigquery-export.sh` - New verification script

## Lessons Learned

1. **Always verify imports**: Silent import failures can cause commands to disappear without obvious errors
2. **Database config consistency**: All modules accessing the database need to understand the Cloud SQL Connector pattern
3. **Test in actual environment**: Local testing won't catch container-specific issues like missing dependencies
4. **Better logging**: Dynamic loading should fail loudly or at least log at ERROR level, not just WARNING
5. **Basic verification**: Should have tested that the command existed before debugging why it wasn't working

## Environment Variables Required

For Cloud SQL Connector mode (production):
```bash
USE_CLOUD_SQL_CONNECTOR=true
CLOUD_SQL_INSTANCE=mizzou-news-crawler:us-central1:mizzou-db-prod
DATABASE_USER=<from secret>
DATABASE_PASSWORD=<from secret>
DATABASE_NAME=<from secret>
GOOGLE_CLOUD_PROJECT=mizzou-news-crawler
```

The telemetry module now properly constructs `postgresql://<user>:<pass>@/<database>` from these components.
