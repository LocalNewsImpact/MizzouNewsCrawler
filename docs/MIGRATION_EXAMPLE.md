# Migration Example: Using Lifecycle Dependency Injection

This document provides a concrete example of migrating an existing endpoint to use the new lifecycle dependency injection system.

## Example: Domain Issues Endpoint

### Before (Using module-level db_manager)

```python
# In backend/app/main.py
from src.models.database import DatabaseManager

# Global database manager created at module import
db_manager = DatabaseManager(app_config.DATABASE_URL)

@app.get("/api/domain_issues")
def get_domain_issues(
    limit: int = 100,
    offset: int = 0,
):
    """Get list of domains with crawl issues."""
    # Uses module-level db_manager directly
    with db_manager.get_session() as session:
        issues = session.query(DomainFeedback)\
            .filter(DomainFeedback.has_issue == True)\
            .order_by(desc(DomainFeedback.updated_at))\
            .limit(limit)\
            .offset(offset)\
            .all()
        
        return {
            "issues": [
                {
                    "host": issue.host,
                    "issue_type": issue.issue_type,
                    "description": issue.description,
                    "updated_at": issue.updated_at.isoformat(),
                }
                for issue in issues
            ],
            "limit": limit,
            "offset": offset,
        }
```

### After (Using dependency injection)

```python
# In backend/app/main.py
from fastapi import Depends, HTTPException
from backend.app.lifecycle import get_db_manager

@app.get("/api/domain_issues")
def get_domain_issues(
    limit: int = 100,
    offset: int = 0,
    db: DatabaseManager | None = Depends(get_db_manager),
):
    """Get list of domains with crawl issues."""
    # Check if database is available
    if not db:
        raise HTTPException(
            status_code=503,
            detail="Database temporarily unavailable"
        )
    
    # Use injected db instead of module-level db_manager
    with db.get_session() as session:
        issues = session.query(DomainFeedback)\
            .filter(DomainFeedback.has_issue == True)\
            .order_by(desc(DomainFeedback.updated_at))\
            .limit(limit)\
            .offset(offset)\
            .all()
        
        return {
            "issues": [
                {
                    "host": issue.host,
                    "issue_type": issue.issue_type,
                    "description": issue.description,
                    "updated_at": issue.updated_at.isoformat(),
                }
                for issue in issues
            ],
            "limit": limit,
            "offset": offset,
        }
```

## Key Changes

1. **Import the dependency function**: 
   ```python
   from backend.app.lifecycle import get_db_manager
   ```

2. **Add dependency to function signature**:
   ```python
   db: DatabaseManager | None = Depends(get_db_manager)
   ```

3. **Check for None and handle gracefully**:
   ```python
   if not db:
       raise HTTPException(503, "Database temporarily unavailable")
   ```

4. **Use injected `db` instead of module-level `db_manager`**:
   ```python
   with db.get_session() as session:
       # ... query code ...
   ```

## Benefits

### Testability

With dependency injection, you can easily override the database in tests:

```python
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.lifecycle import get_db_manager

def test_domain_issues():
    # Create test database
    test_db = DatabaseManager("sqlite:///:memory:")
    
    # Populate test data
    with test_db.get_session() as session:
        session.add(DomainFeedback(
            host="example.com",
            has_issue=True,
            issue_type="403_error",
            description="Blocked by server"
        ))
        session.commit()
    
    # Override dependency
    app.dependency_overrides[get_db_manager] = lambda: test_db
    
    try:
        # Test the endpoint
        client = TestClient(app)
        response = client.get("/api/domain_issues")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["issues"]) == 1
        assert data["issues"][0]["host"] == "example.com"
    finally:
        # Clean up
        app.dependency_overrides.clear()
```

### Graceful Degradation

If the database is temporarily unavailable (e.g., during Cloud SQL maintenance), the endpoint returns a proper 503 error instead of crashing:

```python
if not db:
    raise HTTPException(503, "Database temporarily unavailable")
```

### No Module-Level Side Effects

The old approach created a `DatabaseManager` at module import time, which:
- Made testing harder (had to monkeypatch module attributes)
- Could fail during import if database was unavailable
- Created global state that was hard to reason about

The new approach:
- Creates resources only during app startup
- Makes dependencies explicit in function signatures
- Supports clean test isolation via dependency overrides

## Backward Compatibility

The module-level `db_manager` is still available for existing code:

```python
# Still works (for backward compatibility)
db_manager = DatabaseManager(app_config.DATABASE_URL)
```

However, new endpoints should use dependency injection, and existing endpoints should be migrated gradually.

## Migration Checklist

For each endpoint:

- [ ] Add import: `from backend.app.lifecycle import get_db_manager`
- [ ] Add dependency parameter: `db: DatabaseManager | None = Depends(get_db_manager)`
- [ ] Add None check: `if not db: raise HTTPException(503, "...")`
- [ ] Replace `db_manager` with injected `db` parameter
- [ ] Update tests to use `app.dependency_overrides` instead of monkeypatching
- [ ] Test endpoint with and without database available

## Other Available Dependencies

### TelemetryStore

For endpoints that need to submit telemetry:

```python
from backend.app.lifecycle import get_telemetry_store

@app.post("/api/articles/{idx}/reviews")
def submit_review(
    idx: int,
    review: ReviewIn,
    telemetry: TelemetryStore | None = Depends(get_telemetry_store),
):
    # ... business logic ...
    
    # Optional telemetry submission
    if telemetry:
        telemetry.submit(lambda conn: conn.execute(
            "INSERT INTO review_log (article_id, reviewer, timestamp) VALUES (?, ?, ?)",
            (idx, review.reviewer, datetime.now())
        ))
    
    return {"status": "success"}
```

### HTTP Session

For endpoints that make outbound HTTP requests:

```python
from backend.app.lifecycle import get_http_session

@app.get("/api/fetch_article")
def fetch_article(
    url: str,
    session: requests.Session | None = Depends(get_http_session),
):
    if not session:
        raise HTTPException(503, "HTTP client unavailable")
    
    # Session may have origin proxy adapter installed
    response = session.get(url, timeout=10)
    response.raise_for_status()
    
    return {"content": response.text}
```

## Further Reading

- [docs/LIFECYCLE_MANAGEMENT.md](./LIFECYCLE_MANAGEMENT.md) - Complete lifecycle documentation
- [FastAPI Dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/)
- [Testing FastAPI](https://fastapi.tiangolo.com/tutorial/testing/)
