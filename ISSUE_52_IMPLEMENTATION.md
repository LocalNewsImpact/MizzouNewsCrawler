# Issue #52 Implementation Summary

## Overview

This document summarizes the implementation of [Issue #52: FastAPI lifecycle management](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/52).

## What Was Implemented

### 1. Lifecycle Management Module (`backend/app/lifecycle.py`)

Created a centralized module that manages the lifecycle of shared resources:

**Startup Phase:**
- Initializes `TelemetryStore` with configurable async writes
- Creates `DatabaseManager` with Cloud SQL or SQLite support
- Sets up shared `requests.Session` 
- Installs origin proxy adapter if `USE_ORIGIN_PROXY=true`
- Sets `app.state.ready = True` to indicate readiness

**Shutdown Phase:**
- Gracefully shuts down `TelemetryStore` (flushes pending writes, stops worker thread)
- Disposes `DatabaseManager` engine and connection pool
- Closes HTTP session to free sockets
- Clears ready flag

### 2. Dependency Injection Functions

Provided clean dependency injection functions for route handlers:

- `get_telemetry_store(request)` - Returns shared TelemetryStore or None
- `get_db_manager(request)` - Returns shared DatabaseManager or None
- `get_http_session(request)` - Returns shared HTTP session (with optional proxy) or None
- `is_ready(request)` - Returns True if app completed startup successfully
- `check_db_health(db_manager)` - Performs lightweight database health check

### 3. Integration with Main App

Updated `backend/app/main.py`:
- Added call to `setup_lifecycle_handlers(app)` to register startup/shutdown handlers
- Kept backward-compatible module-level `db_manager` for existing code
- Module-level instance will be gradually phased out as endpoints migrate

### 4. Enhanced Health Checks

**`/health` endpoint:**
- Basic health check that always returns 200 OK
- Suitable for load balancer probes

**`/ready` endpoint (NEW):**
- Comprehensive readiness check
- Verifies startup completed (`app.state.ready == True`)
- Tests database connectivity with `SELECT 1`
- Reports availability of telemetry, database, and HTTP session
- Returns 503 if not ready (prevents traffic before initialization complete)

### 5. Test Infrastructure

**Test Module (`tests/backend/test_lifecycle.py`):**
- Tests for startup/shutdown handler registration
- Tests for resource initialization (telemetry, database, HTTP session)
- Tests for graceful cleanup on shutdown
- Tests for dependency injection functions
- Tests for dependency overrides in test scenarios
- Tests for origin proxy installation when env var set
- Tests for database health checks

**Global Test Configuration (`tests/conftest.py`):**
- Added `TELEMETRY_ASYNC_WRITES=false` to prevent background thread issues in tests
- Added `clean_app_state` fixture to ensure clean app state between backend tests
- Ensures test isolation and deterministic test behavior

### 6. Documentation

**Comprehensive Lifecycle Documentation (`docs/LIFECYCLE_MANAGEMENT.md`):**
- Architecture overview (startup/shutdown phases)
- Usage guide for application code and route handlers
- Guide for test setup and dependency overrides
- Configuration reference (environment variables)
- Best practices for production and testing
- Troubleshooting guide

**Migration Example (`docs/MIGRATION_EXAMPLE.md`):**
- Concrete before/after example of endpoint migration
- Step-by-step migration checklist
- Testability improvements shown with examples
- Examples for all available dependencies

**Backend README Update (`backend/README.md`):**
- Added lifecycle management section
- Links to detailed documentation
- Health check endpoint descriptions

## Key Features

### Backward Compatibility

- Existing module-level `db_manager` still works
- No breaking changes to existing endpoints
- Migration can happen gradually
- Existing tests continue to work

### Graceful Degradation

- Resources may be `None` if initialization failed
- Endpoints check for `None` and return 503 if unavailable
- App continues running even if optional resources (like telemetry) fail to initialize
- Critical resources (like database) cause readiness check to fail

### Testability

Three ways to override dependencies in tests:

1. **Dependency overrides** (recommended):
   ```python
   app.dependency_overrides[get_db_manager] = lambda: test_db
   ```

2. **Monkeypatch app.state**:
   ```python
   app.state.db_manager = test_db
   ```

3. **Use `clean_app_state` fixture**:
   ```python
   def test_something(clean_app_state):
       clean_app_state.state.db_manager = test_db
       # ... test code ...
   ```

### Configuration

All resources respect environment variables:

| Variable | Effect |
|----------|--------|
| `TELEMETRY_ASYNC_WRITES` | Enable/disable background telemetry writer (default: `true`) |
| `USE_ORIGIN_PROXY` | Install origin proxy adapter on HTTP session (default: `false`) |
| `ORIGIN_PROXY_URL` | Base URL for origin proxy |
| `PROXY_USERNAME` / `PROXY_PASSWORD` | Credentials for proxy authentication |

## What's Not Yet Migrated

The following areas still use module-level resources and could benefit from future migration:

1. **Existing route handlers**: Still use module-level `db_manager` directly
2. **Snapshot writer thread**: Still has its own startup/shutdown handlers (lines 320-339 in main.py)
3. **Table initialization handlers**: Still have separate startup handlers (lines 342-350 in main.py)

These are intentionally left as-is to minimize the scope of changes and maintain backward compatibility. They can be migrated in future PRs.

## Acceptance Criteria from Issue #52

✅ **Single place (FastAPI startup) creates telemetry, DB, http session and origin-proxy installation**
   - Implemented in `backend/app/lifecycle.py` startup handler

✅ **Shutdown handler cleanly closes telemetry writer, DB engine, and HTTP session**
   - Implemented in `backend/app/lifecycle.py` shutdown handler
   - Calls `telemetry_store.shutdown(wait=True)`, `engine.dispose()`, `session.close()`

✅ **Route handlers obtain these resources via DI (app.state or dependency functions)**
   - Dependency functions provided: `get_telemetry_store`, `get_db_manager`, `get_http_session`
   - Example usage shown in documentation

✅ **Tests can override resources via TestClient/app.dependency_overrides or via monkeypatching app.state**
   - Both approaches supported and documented
   - Test examples provided in test module and documentation

✅ **Readiness endpoint checks minimal readiness: DB accessible, telemetry store available, app.state.ready is True**
   - `/ready` endpoint implemented
   - Checks database connectivity with `SELECT 1`
   - Reports all resource availability
   - Returns 503 if not ready

## Testing

### How to Run Tests

```bash
# Run all lifecycle tests
pytest tests/backend/test_lifecycle.py -v

# Run with coverage
pytest tests/backend/test_lifecycle.py --cov=backend.app.lifecycle --cov-report=term-missing
```

### What's Tested

- Startup handler registration
- Resource initialization (telemetry, database, HTTP session, ready flag)
- Shutdown cleanup (telemetry flush, engine disposal, session close)
- Dependency injection for all resources
- Dependency overrides in test scenarios
- Origin proxy installation based on environment variable
- Database health checks (success and failure cases)

## Production Deployment Notes

### Environment Variables

Set these in your Cloud Run / GKE deployment:

```bash
# Enable async telemetry writes (recommended for production)
TELEMETRY_ASYNC_WRITES=true

# If using origin proxy for outbound requests
USE_ORIGIN_PROXY=true
ORIGIN_PROXY_URL=https://proxy.example.com
PROXY_USERNAME=your_username
PROXY_PASSWORD=your_password

# Database connection (already configured)
DATABASE_URL=postgresql://user:pass@host/db
# or for Cloud SQL:
USE_CLOUD_SQL_CONNECTOR=true
CLOUD_SQL_INSTANCE=project:region:instance
```

### Health Check Configuration

Configure your orchestration system to use the readiness endpoint:

**Kubernetes:**
```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 10

readinessProbe:
  httpGet:
    path: /ready
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 5
  failureThreshold: 3
```

**Cloud Run:**
```yaml
apiVersion: serving.knative.dev/v1
kind: Service
spec:
  template:
    spec:
      containers:
      - image: gcr.io/project/image
        ports:
        - containerPort: 8000
        livenessProbe:
          httpGet:
            path: /health
        startupProbe:
          httpGet:
            path: /ready
```

## Migration Path for Existing Code

See [docs/MIGRATION_EXAMPLE.md](docs/MIGRATION_EXAMPLE.md) for a detailed example.

**Summary:**
1. Add dependency injection to route handler signature
2. Check for None and return 503 if unavailable
3. Use injected resource instead of module-level variable
4. Update tests to use `app.dependency_overrides`

This can be done gradually, one endpoint at a time.

## Files Changed

```
backend/app/lifecycle.py              (NEW) - Lifecycle management module
backend/app/main.py                    (MODIFIED) - Integrated lifecycle handlers
tests/backend/test_lifecycle.py        (NEW) - Lifecycle tests
tests/conftest.py                      (MODIFIED) - Added telemetry config and fixture
docs/LIFECYCLE_MANAGEMENT.md           (NEW) - Comprehensive documentation
docs/MIGRATION_EXAMPLE.md              (NEW) - Migration guide
backend/README.md                      (MODIFIED) - Added lifecycle section
```

## Next Steps (Optional Future Work)

1. **Migrate existing endpoints** to use dependency injection (non-breaking, can be done gradually)
2. **Consolidate startup handlers** - Move snapshot writer and table init into lifecycle module
3. **Add metrics** - Track resource initialization time, shutdown duration
4. **Add more health checks** - HTTP session connectivity, telemetry queue depth
5. **Document common patterns** - Add more examples for complex scenarios

## References

- [Issue #52](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/52)
- [FastAPI Lifespan Events](https://fastapi.tiangolo.com/advanced/events/)
- [FastAPI Dependency Injection](https://fastapi.tiangolo.com/tutorial/dependencies/)
- [SQLAlchemy Engine Disposal](https://docs.sqlalchemy.org/en/14/core/connections.html#engine-disposal)
