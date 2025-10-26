# FastAPI Lifecycle Flow Diagram

## Application Lifecycle

```
┌─────────────────────────────────────────────────────────────────┐
│                        App Startup                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  setup_lifecycle_handlers(app)                                  │
│  ├─ Registers @app.on_event("startup")                          │
│  └─ Registers @app.on_event("shutdown")                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Startup Handler Runs                         │
├─────────────────────────────────────────────────────────────────┤
│  1. Initialize TelemetryStore                                   │
│     ├─ Create SQLAlchemy engine                                 │
│     ├─ Start background writer thread (if async_writes=true)   │
│     └─ Attach to app.state.telemetry_store                      │
│                                                                  │
│  2. Initialize DatabaseManager                                  │
│     ├─ Create SQLAlchemy engine                                 │
│     ├─ Configure connection pool                                │
│     └─ Attach to app.state.db_manager                           │
│                                                                  │
│  3. Initialize HTTP Session                                     │
│     ├─ Create requests.Session                                  │
│     ├─ Install origin proxy adapter (if USE_ORIGIN_PROXY=true) │
│     └─ Attach to app.state.http_session                         │
│                                                                  │
│  4. Set Ready Flag                                              │
│     └─ app.state.ready = True                                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│               Application Ready to Serve Traffic                │
├─────────────────────────────────────────────────────────────────┤
│  /health  → Returns 200 OK (basic liveness check)              │
│  /ready   → Returns 200 OK + resource status (readiness check) │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │  (handles requests...)
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                 Request Processing Flow                         │
├─────────────────────────────────────────────────────────────────┤
│  Request arrives                                                │
│     │                                                            │
│     ▼                                                            │
│  Route handler invoked                                          │
│     │                                                            │
│     ▼                                                            │
│  Dependencies resolved via get_*() functions                    │
│     ├─ get_db_manager(request) → app.state.db_manager          │
│     ├─ get_telemetry_store(request) → app.state.telemetry_store│
│     └─ get_http_session(request) → app.state.http_session      │
│     │                                                            │
│     ▼                                                            │
│  Handler executes with injected resources                       │
│     ├─ Uses db for queries                                      │
│     ├─ Submits telemetry events (async)                         │
│     └─ Makes HTTP requests via session                          │
│     │                                                            │
│     ▼                                                            │
│  Response returned to client                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │  (shutdown signal received)
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Shutdown Handler Runs                         │
├─────────────────────────────────────────────────────────────────┤
│  1. Shutdown TelemetryStore                                     │
│     ├─ Stop background writer thread                            │
│     ├─ Flush all pending writes                                 │
│     └─ Wait for thread to finish (wait=True)                    │
│                                                                  │
│  2. Dispose DatabaseManager                                     │
│     ├─ Close all active connections                             │
│     └─ Dispose engine and connection pool                       │
│                                                                  │
│  3. Close HTTP Session                                          │
│     └─ Close session and free sockets                           │
│                                                                  │
│  4. Clear Ready Flag                                            │
│     └─ app.state.ready = False                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      App Shutdown Complete                      │
└─────────────────────────────────────────────────────────────────┘
```

## Dependency Injection Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  Route Handler Definition                                       │
├─────────────────────────────────────────────────────────────────┤
│  @app.get("/api/articles")                                      │
│  def list_articles(                                             │
│      limit: int = 100,                                          │
│      db: DatabaseManager | None = Depends(get_db_manager)      │
│  ):                                                              │
│      if not db:                                                 │
│          raise HTTPException(503, "Database unavailable")       │
│      ...                                                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │  (request arrives)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI Dependency Resolution                                  │
├─────────────────────────────────────────────────────────────────┤
│  1. Identify dependencies (Depends(...))                        │
│  2. Call get_db_manager(request)                                │
│  3. get_db_manager returns app.state.db_manager                 │
│  4. Inject resolved value into handler                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Handler Execution                                              │
├─────────────────────────────────────────────────────────────────┤
│  def list_articles(limit=100, db=<DatabaseManager instance>):   │
│      # db is now available                                      │
│      with db.get_session() as session:                          │
│          articles = session.query(Article).limit(limit).all()   │
│      return {"articles": [a.to_dict() for a in articles]}       │
└─────────────────────────────────────────────────────────────────┘
```

## Test Dependency Override Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  Test Setup                                                     │
├─────────────────────────────────────────────────────────────────┤
│  # Create test database                                         │
│  test_db = DatabaseManager("sqlite:///:memory:")                │
│                                                                  │
│  # Override dependency                                          │
│  app.dependency_overrides[get_db_manager] = lambda: test_db    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Test Execution                                                 │
├─────────────────────────────────────────────────────────────────┤
│  client = TestClient(app)                                       │
│  response = client.get("/api/articles?limit=10")               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI Dependency Resolution (in test)                        │
├─────────────────────────────────────────────────────────────────┤
│  1. Check app.dependency_overrides for get_db_manager           │
│  2. Override found! Call lambda: test_db                        │
│  3. Inject test_db instead of app.state.db_manager             │
│  4. Handler executes with test database                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Test Assertion                                                 │
├─────────────────────────────────────────────────────────────────┤
│  assert response.status_code == 200                             │
│  assert len(response.json()["articles"]) <= 10                  │
└─────────────────────────────────────────────────────────────────┘
```

## Resource State Transitions

```
TelemetryStore State:
    [Not Created] ──startup──> [Initialized] ──submit()──> [Writing Async]
                                     │                            │
                                     └───────────────┬────────────┘
                                                     │
                                          shutdown(wait=True)
                                                     │
                                                     ▼
                                              [Flushing] ──> [Stopped]

DatabaseManager State:
    [Not Created] ──startup──> [Engine Created] ──get_session()──> [Session Active]
                                      │                                    │
                                      └────────────────┬───────────────────┘
                                                       │
                                                 engine.dispose()
                                                       │
                                                       ▼
                                                  [Disposed]

HTTP Session State:
    [Not Created] ──startup──> [Session Created] ──request()──> [Request Active]
                                      │                                │
                      (if USE_ORIGIN_PROXY)                           │
                                      │                                │
                               enable_origin_proxy()                  │
                                      │                                │
                                [Proxy Enabled] <────────────────────┘
                                      │
                                 session.close()
                                      │
                                      ▼
                                   [Closed]
```

## Error Handling Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  Resource Initialization Error (Startup)                        │
├─────────────────────────────────────────────────────────────────┤
│  try:                                                            │
│      telemetry_store = TelemetryStore(...)                      │
│      app.state.telemetry_store = telemetry_store                │
│  except Exception as exc:                                       │
│      logger.exception("Failed to initialize TelemetryStore")    │
│      app.state.telemetry_store = None  # Continue without it    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Route Handler Checks for None                                  │
├─────────────────────────────────────────────────────────────────┤
│  def handler(db: DatabaseManager | None = Depends(...)):        │
│      if not db:                                                 │
│          raise HTTPException(503, "Database unavailable")       │
│      # Proceed with db operations                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Client Receives 503 Service Unavailable                        │
│  Body: {"detail": "Database unavailable"}                       │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  /ready Endpoint Error Handling                                 │
├─────────────────────────────────────────────────────────────────┤
│  1. Check app.state.ready → False?                              │
│     Return 503 "Application not ready: startup incomplete"      │
│                                                                  │
│  2. Check database health → SELECT 1 fails?                     │
│     Return 503 "Application not ready: Database connection..."  │
│                                                                  │
│  3. All checks pass?                                            │
│     Return 200 OK with resource status                          │
└─────────────────────────────────────────────────────────────────┘
```

## Key Design Principles

1. **Fail Gracefully**: Non-critical resources (telemetry) return None if initialization fails
2. **Explicit Dependencies**: All dependencies declared in function signatures
3. **Early Validation**: Resources checked for None before use
4. **Clean Shutdown**: All resources disposed in reverse order of creation
5. **Test Isolation**: Dependency overrides ensure tests don't affect each other
