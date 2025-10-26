# FastAPI Lifecycle Management

This document describes the centralized lifecycle management system for the MizzouNewsCrawler FastAPI backend, implemented as part of [Issue #52](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/52).

## Overview

The lifecycle management system centralizes the initialization and cleanup of shared resources:

- **TelemetryStore**: Background telemetry writer with thread management
- **DatabaseManager**: SQLAlchemy engine and connection pool
- **HTTP Session**: Shared `requests.Session` with optional origin proxy adapter
- **Other long-lived resources**: Caches, thread pools, etc.

## Benefits

1. **Single source of truth**: All resource initialization happens in one place (`backend/app/lifecycle.py`)
2. **Proper cleanup**: Resources are gracefully shut down on app termination
3. **Testability**: Dependencies can be easily overridden in tests
4. **Production-ready**: Supports health/readiness checks for orchestration systems

## Architecture

### Startup Phase

When the FastAPI application starts, the lifecycle handlers:

1. Create a `TelemetryStore` instance with configurable async writes
2. Initialize `DatabaseManager` with the configured database URL
3. Create a shared `requests.Session`
4. Install the origin proxy adapter if `USE_ORIGIN_PROXY=true`
5. Set `app.state.ready = True` to indicate readiness

All resources are attached to `app.state` for easy access.

### Shutdown Phase

When the application shuts down (gracefully or via signal), the handlers:

1. Call `telemetry_store.shutdown(wait=True)` to flush pending writes
2. Call `db_manager.engine.dispose()` to close connection pool
3. Call `http_session.close()` to free sockets and connections
4. Clear `app.state.ready` flag

## Usage

### In Application Code

```python
from backend.app.lifecycle import setup_lifecycle_handlers

app = FastAPI()
setup_lifecycle_handlers(app)
```

This is already done in `backend/app/main.py`.

### In Route Handlers

Use dependency injection to access shared resources:

```python
from fastapi import Depends
from backend.app.lifecycle import get_db_manager, get_telemetry_store

@app.get("/articles")
def list_articles(
    db: DatabaseManager = Depends(get_db_manager),
    telemetry: TelemetryStore | None = Depends(get_telemetry_store),
):
    if not db:
        raise HTTPException(503, "Database unavailable")
    
    with db.get_session() as session:
        articles = session.query(Article).limit(10).all()
    
    if telemetry:
        telemetry.submit(lambda conn: conn.execute(
            "INSERT INTO access_log (endpoint, timestamp) VALUES (?, ?)",
            ("/articles", datetime.now())
        ))
    
    return {"articles": [a.to_dict() for a in articles]}
```

### In Tests

Override dependencies to inject test doubles:

```python
from fastapi.testclient import TestClient
from backend.app.lifecycle import get_db_manager
from backend.app.main import app

def test_list_articles():
    # Create a test database manager
    test_db = DatabaseManager("sqlite:///:memory:")
    
    # Override the dependency
    app.dependency_overrides[get_db_manager] = lambda: test_db
    
    with TestClient(app) as client:
        response = client.get("/articles")
        assert response.status_code == 200
    
    # Clean up override
    app.dependency_overrides.clear()
```

Or monkeypatch `app.state` directly:

```python
def test_with_mock_telemetry():
    from unittest.mock import MagicMock
    
    mock_store = MagicMock()
    app.state.telemetry_store = mock_store
    
    with TestClient(app) as client:
        response = client.get("/articles")
    
    # Verify telemetry was called
    mock_store.submit.assert_called()
```

## Available Dependencies

### `get_telemetry_store(request: Request) -> TelemetryStore | None`

Returns the shared `TelemetryStore` instance, or `None` if unavailable.

**When to use**: When you need to submit telemetry events (e.g., HTTP status, operation tracking).

### `get_db_manager(request: Request) -> DatabaseManager | None`

Returns the shared `DatabaseManager` instance, or `None` if unavailable.

**When to use**: For all database operations. Always check for `None` and raise `HTTPException(503)` if unavailable.

### `get_http_session(request: Request) -> requests.Session | None`

Returns the shared HTTP session, with origin proxy adapter installed if configured.

**When to use**: When making outbound HTTP requests (e.g., fetching RSS feeds, scraping content).

### `is_ready(request: Request) -> bool`

Returns `True` if the application completed startup successfully.

**When to use**: In health check endpoints to verify readiness.

## Health and Readiness Endpoints

### `/health`

Basic health check that always returns 200 OK. Use for load balancer probes that need a quick response.

### `/ready`

Comprehensive readiness check that:
- Verifies startup completed (`app.state.ready == True`)
- Performs a database connection test (`SELECT 1`)
- Reports availability of all resources

Returns 503 if not ready. Use for orchestration systems (Kubernetes, Cloud Run) that need to know when to route traffic.

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEMETRY_ASYNC_WRITES` | `true` | Enable background telemetry writer thread |
| `USE_ORIGIN_PROXY` | `false` | Install origin proxy adapter on HTTP session |
| `ORIGIN_PROXY_URL` | - | Base URL for origin proxy |
| `PROXY_USERNAME` | - | Username for proxy authentication |
| `PROXY_PASSWORD` | - | Password for proxy authentication |

### Telemetry Async Writes

Set `TELEMETRY_ASYNC_WRITES=false` in tests or development to make telemetry writes synchronous. This simplifies debugging and avoids background thread issues in short-lived test processes.

```python
# In tests/conftest.py
import os
os.environ["TELEMETRY_ASYNC_WRITES"] = "false"
```

### Origin Proxy

When `USE_ORIGIN_PROXY=true`, all HTTP requests made through the shared session are rewritten to route through an origin-style proxy:

```
Original: https://example.com/article.html
Proxied:  {ORIGIN_PROXY_URL}/?url=https%3A%2F%2Fexample.com%2Farticle.html
```

Basic authentication is added automatically if `PROXY_USERNAME` and `PROXY_PASSWORD` are set.

## Migration Guide

### Migrating Existing Code

#### Before (scattered initialization)

```python
from src.models.database import DatabaseManager
from src.telemetry.store import get_store

# Global instances created at import time
db_manager = DatabaseManager("sqlite:///data/mizzou.db")
telemetry = get_store()

@app.get("/articles")
def list_articles():
    with db_manager.get_session() as session:
        articles = session.query(Article).all()
    return {"articles": articles}
```

#### After (dependency injection)

```python
from fastapi import Depends
from backend.app.lifecycle import get_db_manager, get_telemetry_store

@app.get("/articles")
def list_articles(
    db: DatabaseManager = Depends(get_db_manager),
):
    if not db:
        raise HTTPException(503, "Database unavailable")
    
    with db.get_session() as session:
        articles = session.query(Article).all()
    return {"articles": articles}
```

### Migrating Tests

#### Before (module-level setup)

```python
import backend.app.main as main_module

def test_articles():
    # Monkeypatch module-level db_manager
    test_db = DatabaseManager("sqlite:///:memory:")
    main_module.db_manager = test_db
    
    client = TestClient(main_module.app)
    response = client.get("/articles")
    assert response.status_code == 200
```

#### After (dependency override)

```python
from backend.app.main import app
from backend.app.lifecycle import get_db_manager

def test_articles():
    test_db = DatabaseManager("sqlite:///:memory:")
    
    # Override dependency
    app.dependency_overrides[get_db_manager] = lambda: test_db
    
    client = TestClient(app)
    response = client.get("/articles")
    assert response.status_code == 200
    
    # Clean up
    app.dependency_overrides.clear()
```

## Best Practices

### 1. Always check for None

Dependencies may return `None` if initialization failed. Always handle this case:

```python
@app.get("/data")
def get_data(db: DatabaseManager | None = Depends(get_db_manager)):
    if not db:
        raise HTTPException(503, "Service temporarily unavailable")
    # ...
```

### 2. Use dependency overrides in tests

Don't monkeypatch `app.state` directly unless necessary. Use `app.dependency_overrides` for cleaner test isolation:

```python
app.dependency_overrides[get_db_manager] = lambda: test_db
```

### 3. Disable async telemetry in tests

Set `TELEMETRY_ASYNC_WRITES=false` to avoid background thread issues in tests:

```python
# tests/conftest.py
os.environ["TELEMETRY_ASYNC_WRITES"] = "false"
```

### 4. Leverage readiness checks

Use `/ready` for orchestration readiness probes to ensure the app doesn't receive traffic until fully initialized.

### 5. Clean up test overrides

Always clear dependency overrides after tests to prevent state leakage:

```python
try:
    app.dependency_overrides[get_db_manager] = test_db
    # ... test code ...
finally:
    app.dependency_overrides.clear()
```

## Troubleshooting

### Startup Failures

If startup fails (e.g., database unreachable), the app will continue but set affected resources to `None`. Check logs for:

```
ERROR: Failed to initialize DatabaseManager: <error details>
```

The `/ready` endpoint will return 503 until the issue is resolved.

### Shutdown Hangs

If shutdown hangs, check for:
- Long-running telemetry writes (increase `timeout` in `TelemetryStore.__init__`)
- Unclosed database sessions (ensure all `with db.get_session()` blocks exit)
- HTTP requests in progress (ensure requests have timeouts)

### Tests Failing with "Database unavailable"

Ensure test dependencies are properly overridden:

```python
app.dependency_overrides[get_db_manager] = lambda: test_db
```

Or set up a test database in `conftest.py`:

```python
@pytest.fixture(autouse=True)
def setup_test_db():
    test_db = DatabaseManager("sqlite:///:memory:")
    app.state.db_manager = test_db
    yield
    app.state.db_manager = None
```

## Further Reading

- [Issue #52: FastAPI lifecycle management](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/52)
- [FastAPI Lifespan Events](https://fastapi.tiangolo.com/advanced/events/)
- [FastAPI Dependency Injection](https://fastapi.tiangolo.com/tutorial/dependencies/)
- [Testing FastAPI Applications](https://fastapi.tiangolo.com/tutorial/testing/)
