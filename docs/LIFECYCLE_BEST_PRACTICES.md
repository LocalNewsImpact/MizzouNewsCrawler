# Lifecycle Management Best Practices

## Production Deployment

### 1. Always Configure Readiness Probes

Configure your orchestration system to use the `/ready` endpoint to ensure traffic isn't routed until resources are available.

**Good:**
```yaml
readinessProbe:
  httpGet:
    path: /ready
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 5
```

**Bad:**
```yaml
# No readiness probe configured
# Traffic may arrive before database is ready
```

### 2. Set Appropriate Timeouts

Ensure startup and shutdown have sufficient time for cleanup:

**Good:**
```yaml
terminationGracePeriodSeconds: 30  # Kubernetes
```

**Bad:**
```yaml
terminationGracePeriodSeconds: 1  # Too short, telemetry may not flush
```

### 3. Monitor Resource Health

Monitor the `/ready` endpoint and alert if it returns 503 for extended periods:

```bash
# Example monitoring check
curl -f http://localhost:8000/ready || alert "App not ready"
```

### 4. Use Async Telemetry in Production

```bash
# Production environment
TELEMETRY_ASYNC_WRITES=true  # Default, good for performance
```

**Rationale**: Async writes prevent request handlers from blocking on telemetry I/O.

## Development and Testing

### 1. Use Synchronous Telemetry in Tests

```python
# tests/conftest.py
os.environ["TELEMETRY_ASYNC_WRITES"] = "false"
```

**Rationale**: Avoids background thread issues and makes tests deterministic.

### 2. Always Clean Up Dependency Overrides

**Good:**
```python
def test_something():
    app.dependency_overrides[get_db_manager] = lambda: test_db
    try:
        # Test code
        pass
    finally:
        app.dependency_overrides.clear()
```

**Bad:**
```python
def test_something():
    app.dependency_overrides[get_db_manager] = lambda: test_db
    # Test code
    # No cleanup - affects subsequent tests!
```

### 3. Use the clean_app_state Fixture

```python
def test_with_custom_state(clean_app_state):
    # Modify app state
    clean_app_state.state.custom_value = "test"
    # Automatic cleanup after test
```

**Rationale**: Prevents state leakage between tests.

## Route Handler Patterns

### 1. Always Check for None

**Good:**
```python
@app.get("/articles")
def list_articles(db: DatabaseManager | None = Depends(get_db_manager)):
    if not db:
        raise HTTPException(503, "Database unavailable")
    # Proceed safely
```

**Bad:**
```python
@app.get("/articles")
def list_articles(db: DatabaseManager = Depends(get_db_manager)):
    # No None check - will fail if db is unavailable
    with db.get_session() as session:  # May crash!
        pass
```

### 2. Handle Optional Resources Gracefully

For non-critical resources like telemetry:

**Good:**
```python
@app.post("/articles")
def create_article(
    article: ArticleIn,
    db: DatabaseManager | None = Depends(get_db_manager),
    telemetry: TelemetryStore | None = Depends(get_telemetry_store),
):
    if not db:
        raise HTTPException(503, "Database unavailable")
    
    # Save article
    with db.get_session() as session:
        new_article = Article(**article.dict())
        session.add(new_article)
        session.commit()
    
    # Optional telemetry - doesn't fail if unavailable
    if telemetry:
        telemetry.submit(lambda conn: log_creation(conn, new_article.id))
    
    return {"id": new_article.id}
```

**Bad:**
```python
@app.post("/articles")
def create_article(
    article: ArticleIn,
    telemetry: TelemetryStore = Depends(get_telemetry_store),  # No None type!
):
    # Assumes telemetry is always available
    telemetry.submit(...)  # Crashes if telemetry failed to initialize
```

### 3. Combine Multiple Dependencies

```python
@app.post("/fetch-and-save")
def fetch_and_save(
    url: str,
    db: DatabaseManager | None = Depends(get_db_manager),
    session: requests.Session | None = Depends(get_http_session),
):
    if not db:
        raise HTTPException(503, "Database unavailable")
    if not session:
        raise HTTPException(503, "HTTP client unavailable")
    
    # Both resources available
    response = session.get(url, timeout=10)
    with db.get_session() as db_session:
        # Save result
        pass
```

## Common Pitfalls

### 1. Forgetting to Clear Dependency Overrides

**Problem:**
```python
def test_articles():
    app.dependency_overrides[get_db_manager] = lambda: test_db
    # Test code
    # No cleanup!

def test_reviews():
    # Still using test_db from previous test!
    client = TestClient(app)
    response = client.get("/reviews")  # Unexpected behavior
```

**Solution:**
```python
@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()
```

### 2. Not Handling Startup Failures

**Problem:**
```python
# Startup handler
telemetry_store = TelemetryStore(...)  # Raises exception
app.state.telemetry_store = telemetry_store  # Never reached
# App crashes on startup
```

**Solution:**
```python
# Startup handler (already implemented in lifecycle.py)
try:
    telemetry_store = TelemetryStore(...)
    app.state.telemetry_store = telemetry_store
except Exception as exc:
    logger.exception("Failed to initialize TelemetryStore")
    app.state.telemetry_store = None  # Continue without it
```

### 3. Using Module-Level Resources Instead of Dependencies

**Problem:**
```python
# Old pattern
from backend.app.main import db_manager  # Module-level variable

@app.get("/articles")
def list_articles():
    with db_manager.get_session() as session:  # Hard to test
        pass
```

**Solution:**
```python
# New pattern
from backend.app.lifecycle import get_db_manager

@app.get("/articles")
def list_articles(db: DatabaseManager | None = Depends(get_db_manager)):
    if not db:
        raise HTTPException(503, "Database unavailable")
    with db.get_session() as session:  # Easy to test with overrides
        pass
```

### 4. Not Waiting for Telemetry Flush

**Problem:**
```python
# Startup handler
app.state.telemetry_store = TelemetryStore(async_writes=True)

# Shutdown handler
app.state.telemetry_store.shutdown(wait=False)  # Don't wait!
# Some writes may be lost!
```

**Solution:**
```python
# Shutdown handler (already implemented in lifecycle.py)
app.state.telemetry_store.shutdown(wait=True)  # Wait for flush
```

### 5. Forgetting Timeouts on HTTP Requests

**Problem:**
```python
@app.get("/fetch")
def fetch(url: str, session: requests.Session = Depends(get_http_session)):
    response = session.get(url)  # No timeout! May hang forever
    return response.json()
```

**Solution:**
```python
@app.get("/fetch")
def fetch(url: str, session: requests.Session = Depends(get_http_session)):
    response = session.get(url, timeout=10)  # Always set timeout
    return response.json()
```

## Performance Tips

### 1. Reuse HTTP Session

The shared session reuses connections (HTTP keep-alive):

**Good:**
```python
# Uses shared session (connection pooling)
@app.get("/fetch")
def fetch(url: str, session: requests.Session = Depends(get_http_session)):
    return session.get(url, timeout=10).json()
```

**Bad:**
```python
# Creates new session per request (no connection reuse)
@app.get("/fetch")
def fetch(url: str):
    session = requests.Session()  # New session every time!
    return session.get(url, timeout=10).json()
```

### 2. Use Database Connection Pool

The DatabaseManager uses SQLAlchemy's connection pool:

**Good:**
```python
# Uses connection pool
with db.get_session() as session:
    # Session from pool
    results = session.query(Article).all()
# Connection returned to pool
```

**Bad:**
```python
# Creates new engine every time
engine = create_engine(DATABASE_URL)  # Don't do this!
Session = sessionmaker(bind=engine)
session = Session()
# No connection pooling
```

### 3. Batch Telemetry Writes

Async telemetry batches writes automatically:

**Good:**
```python
# Async writes (batched)
if telemetry:
    for item in items:
        telemetry.submit(lambda conn, i=item: log_item(conn, i))
# Writes batched by background worker
```

**Synchronous Alternative (if needed):**
```python
# Batch manually if using sync writes
if telemetry:
    def batch_write(conn):
        for item in items:
            log_item(conn, item)
    telemetry.submit(batch_write)
```

## Security Considerations

### 1. Validate Proxy Credentials

**Good:**
```python
# Startup handler checks for credentials
if use_origin_proxy:
    proxy_url = os.getenv("ORIGIN_PROXY_URL")
    proxy_user = os.getenv("PROXY_USERNAME")
    proxy_pass = os.getenv("PROXY_PASSWORD")
    
    if not proxy_url:
        logger.error("USE_ORIGIN_PROXY=true but ORIGIN_PROXY_URL not set")
        # Don't install proxy
    elif proxy_user and not proxy_pass:
        logger.warning("PROXY_USERNAME set but PROXY_PASSWORD empty")
    else:
        enable_origin_proxy(session)
```

### 2. Don't Log Sensitive Information

**Good:**
```python
logger.info(f"Database initialized: {database_url[:50]}...")  # Truncate
```

**Bad:**
```python
logger.info(f"Database initialized: {database_url}")  # May contain password
```

### 3. Rotate Proxy Credentials

Ensure proxy credentials are rotated regularly and stored in secrets manager:

```bash
# Store in Cloud Secret Manager
gcloud secrets create proxy-password --data-file=-

# Reference in Cloud Run
gcloud run deploy api \
  --set-secrets="PROXY_PASSWORD=proxy-password:latest"
```

## Monitoring and Observability

### 1. Log Lifecycle Events

The lifecycle module already logs key events:

```python
logger.info("Starting resource initialization...")
logger.info("TelemetryStore initialized (async_writes=true)")
logger.info("DatabaseManager initialized: sqlite://...")
logger.info("HTTP session initialized")
logger.info("All resources initialized, app is ready")
```

Monitor these logs to detect startup issues.

### 2. Track Readiness Check Failures

Monitor `/ready` endpoint failures:

```python
# Example with Prometheus metrics
from prometheus_client import Counter

readiness_failures = Counter('readiness_check_failures_total', 'Number of failed readiness checks')

@app.get("/ready")
async def readiness_check():
    try:
        # Check resources
        if not ready:
            readiness_failures.inc()
            raise HTTPException(503, "Not ready")
        return {"status": "ready"}
    except Exception as exc:
        readiness_failures.inc()
        raise
```

### 3. Expose Resource Metrics

Add metrics about resource health:

```python
from prometheus_client import Gauge

db_connections_active = Gauge('db_connections_active', 'Active database connections')
telemetry_queue_size = Gauge('telemetry_queue_size', 'Telemetry queue depth')

@app.get("/metrics")
def metrics():
    # Update gauges
    if app.state.db_manager:
        db_connections_active.set(app.state.db_manager.engine.pool.size())
    if app.state.telemetry_store:
        telemetry_queue_size.set(app.state.telemetry_store._queue.qsize())
    
    # Return Prometheus metrics
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

## Migration Checklist

When migrating an existing endpoint:

- [ ] Import dependency function (`from backend.app.lifecycle import get_db_manager`)
- [ ] Add dependency parameter (`db: DatabaseManager | None = Depends(get_db_manager)`)
- [ ] Add None check (`if not db: raise HTTPException(503, "...")`)
- [ ] Replace module-level variable (`db_manager` → `db`)
- [ ] Update tests to use `app.dependency_overrides`
- [ ] Test with resource available
- [ ] Test with resource unavailable (should return 503)
- [ ] Verify no breaking changes to API contract

## Summary

**Do:**
- ✅ Use dependency injection for all shared resources
- ✅ Check for None before using resources
- ✅ Clean up dependency overrides in tests
- ✅ Configure readiness probes in production
- ✅ Use async telemetry in production, sync in tests
- ✅ Set timeouts on HTTP requests
- ✅ Monitor `/ready` endpoint health

**Don't:**
- ❌ Use module-level resources in new code
- ❌ Forget to check for None
- ❌ Leave dependency overrides active between tests
- ❌ Skip readiness checks in orchestration
- ❌ Log sensitive information (passwords, tokens)
- ❌ Create new sessions/engines per request
- ❌ Set `wait=False` when shutting down telemetry
