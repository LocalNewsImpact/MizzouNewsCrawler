# Quick Start: Lifecycle Management

> **TL;DR**: This PR implements centralized FastAPI lifecycle management for Issue #52. Resources (telemetry, database, HTTP session) are now initialized at app startup, injected via dependencies, and cleaned up gracefully on shutdown.

## What Changed?

### New Files (2,385 lines added)

**Core Implementation:**
- `backend/app/lifecycle.py` - Startup/shutdown handlers and dependency injection functions
- `tests/backend/test_lifecycle.py` - Comprehensive test suite (20+ tests)

**Documentation:**
- `docs/LIFECYCLE_MANAGEMENT.md` - Complete architecture and usage guide
- `docs/MIGRATION_EXAMPLE.md` - Concrete before/after migration examples
- `docs/LIFECYCLE_FLOW.md` - Visual diagrams of lifecycle flows
- `docs/LIFECYCLE_BEST_PRACTICES.md` - Production and testing best practices
- `ISSUE_52_IMPLEMENTATION.md` - Implementation summary

**Updates:**
- `backend/app/main.py` - Integrated lifecycle handlers, added `/ready` endpoint
- `backend/README.md` - Added lifecycle section
- `tests/conftest.py` - Added telemetry config and `clean_app_state` fixture

## Quick Examples

### Using Dependency Injection in Route Handlers

**Before:**
```python
from backend.app.main import db_manager

@app.get("/articles")
def list_articles():
    with db_manager.get_session() as session:
        return session.query(Article).all()
```

**After:**
```python
from fastapi import Depends, HTTPException
from backend.app.lifecycle import get_db_manager

@app.get("/articles")
def list_articles(db: DatabaseManager | None = Depends(get_db_manager)):
    if not db:
        raise HTTPException(503, "Database unavailable")
    with db.get_session() as session:
        return session.query(Article).all()
```

### Testing with Dependency Overrides

```python
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.lifecycle import get_db_manager

def test_articles():
    test_db = DatabaseManager("sqlite:///:memory:")
    app.dependency_overrides[get_db_manager] = lambda: test_db
    
    try:
        client = TestClient(app)
        response = client.get("/articles")
        assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()
```

## Available Dependencies

| Function | Returns | Use For |
|----------|---------|---------|
| `get_telemetry_store(request)` | `TelemetryStore \| None` | Submitting telemetry events |
| `get_db_manager(request)` | `DatabaseManager \| None` | Database queries |
| `get_http_session(request)` | `requests.Session \| None` | Outbound HTTP requests |
| `is_ready(request)` | `bool` | Checking app readiness |
| `check_db_health(db)` | `(bool, str)` | Database health checks |

## Health Check Endpoints

### `/health`
Basic liveness check - always returns 200 OK.

```bash
curl http://localhost:8000/health
# {"status":"healthy","service":"api"}
```

### `/ready` (NEW)
Readiness check - validates all resources are available.

```bash
curl http://localhost:8000/ready
# {"status":"ready","service":"api","resources":{"database":"available",...}}
```

Returns 503 if:
- Startup incomplete (`app.state.ready != True`)
- Database connection fails
- Critical resources unavailable

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `TELEMETRY_ASYNC_WRITES` | `true` | Enable background telemetry writer |
| `USE_ORIGIN_PROXY` | `false` | Install origin proxy on HTTP session |
| `ORIGIN_PROXY_URL` | - | Base URL for origin proxy |
| `PROXY_USERNAME` | - | Proxy authentication username |
| `PROXY_PASSWORD` | - | Proxy authentication password |

## Key Benefits

1. ✅ **Proper Cleanup**: No leaked threads, connections, or sockets
2. ✅ **Graceful Degradation**: App continues if non-critical resources fail
3. ✅ **Production Ready**: Health checks for K8s/Cloud Run
4. ✅ **Testable**: Easy dependency overrides
5. ✅ **Backward Compatible**: Existing code unchanged

## Testing

Run the lifecycle tests:

```bash
pytest tests/backend/test_lifecycle.py -v
```

All tests pass (20+ test cases covering startup, shutdown, dependencies, overrides).

## Migration Path

### For New Endpoints
Use dependency injection from the start:
```python
from backend.app.lifecycle import get_db_manager

@app.get("/new-endpoint")
def new_endpoint(db: DatabaseManager | None = Depends(get_db_manager)):
    if not db:
        raise HTTPException(503, "Database unavailable")
    # Use db
```

### For Existing Endpoints
Migration is **optional** and **non-breaking**. The module-level `db_manager` still works.

Migrate gradually:
1. Add dependency parameter
2. Add None check
3. Replace `db_manager` with injected `db`
4. Update tests to use `app.dependency_overrides`

See `docs/MIGRATION_EXAMPLE.md` for detailed examples.

## Production Deployment

### Kubernetes
```yaml
readinessProbe:
  httpGet:
    path: /ready
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 5
```

### Cloud Run
```yaml
startupProbe:
  httpGet:
    path: /ready
  initialDelaySeconds: 5
```

### Environment Variables
```bash
TELEMETRY_ASYNC_WRITES=true
USE_ORIGIN_PROXY=true  # If using proxy
ORIGIN_PROXY_URL=https://proxy.example.com
PROXY_USERNAME=...
PROXY_PASSWORD=...
```

## Documentation Structure

- **Quick Start** (this file) - Get started quickly
- **docs/LIFECYCLE_MANAGEMENT.md** - Complete architecture guide
- **docs/MIGRATION_EXAMPLE.md** - Step-by-step migration examples
- **docs/LIFECYCLE_FLOW.md** - Visual flow diagrams
- **docs/LIFECYCLE_BEST_PRACTICES.md** - Production and testing patterns
- **ISSUE_52_IMPLEMENTATION.md** - Full implementation details

## What's NOT Changed?

✅ **Backward Compatible**
- Module-level `db_manager` still works
- Existing endpoints unchanged
- Existing tests pass
- No breaking changes

## Next Steps (Optional)

1. **Test in staging** - Deploy and verify `/ready` endpoint works
2. **Configure probes** - Update K8s/Cloud Run config to use `/ready`
3. **Migrate endpoints** - Gradually update route handlers (optional)
4. **Monitor health** - Alert on `/ready` returning 503

## Questions?

See the detailed documentation:
- Architecture: `docs/LIFECYCLE_MANAGEMENT.md`
- Migration: `docs/MIGRATION_EXAMPLE.md`
- Best practices: `docs/LIFECYCLE_BEST_PRACTICES.md`

Or check the implementation summary: `ISSUE_52_IMPLEMENTATION.md`

## Summary

✅ All requirements from Issue #52 implemented
✅ 2,385 lines of code and documentation added
✅ 20+ test cases passing
✅ Zero breaking changes
✅ Production ready

The lifecycle management system is ready for deployment and use. 🚀
