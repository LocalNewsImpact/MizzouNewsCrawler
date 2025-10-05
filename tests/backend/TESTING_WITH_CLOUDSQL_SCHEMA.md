# Testing Against CloudSQL Schema Locally

This document explains how to write reliable tests for FastAPI endpoints that query CloudSQL database, using local in-memory SQLite with the same schema.

## Overview

The test infrastructure allows you to:
- Test against the **actual CloudSQL schema** (not CSV files)
- Run tests **locally** without needing a CloudSQL instance
- Use **in-memory SQLite** for fast, isolated test execution
- Share database state between **fixtures and endpoints**

## Key Components

### 1. Database Engine Mocking (StaticPool)

```python
@pytest.fixture(scope="function")
def db_engine():
    """Create in-memory SQLite database for testing."""
    from sqlalchemy.pool import StaticPool
    
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # Critical: shares connection across threads
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()
```

**Why StaticPool?** 
- In-memory SQLite databases normally exist only for one connection
- FastAPI TestClient runs in a different thread than pytest fixtures
- StaticPool ensures all connections (fixture setup + endpoint queries) see the same database

### 2. Test Client with Engine-Level Mocking

```python
@pytest.fixture
def test_client(db_engine, monkeypatch):
    """Create FastAPI test client with mocked database engine."""
    from contextlib import contextmanager
    from backend.app import main
    
    # Mock the DatabaseManager's engine with our test engine
    monkeypatch.setattr(main.db_manager, "engine", db_engine)
    
    # Mock get_session to use the test engine
    @contextmanager
    def mock_get_session_context():
        SessionLocal = sessionmaker(bind=db_engine)
        session = SessionLocal()
        try:
            yield session
            session.commit()  # Commit so changes are visible
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    def mock_get_session():
        return mock_get_session_context()
    
    monkeypatch.setattr(main.db_manager, "get_session", mock_get_session)
    
    client = TestClient(app)
    return client
```

**Why engine-level mocking?**
- We mock `db_manager.engine` directly, not just `get_session()`
- This ensures all database operations in endpoints use the test database
- We also mock `get_session()` to use the test engine with proper commit behavior

### 3. CloudSQL Schema Fixtures

All fixtures use the **actual CloudSQL production schema**:

```python
@pytest.fixture
def sample_sources(db_session) -> List[Source]:
    """Create sample news sources using CloudSQL schema."""
    sources = [
        Source(
            id="source-1",
            host="columbiatribune.com",              # NOT "domain"
            host_norm="columbiatribune.com",
            canonical_name="Columbia Daily Tribune",  # NOT "name"
            county="Boone",
            status="active",
        ),
    ]
    for source in sources:
        db_session.add(source)
    db_session.commit()
    return sources

@pytest.fixture
def sample_articles(db_session, sample_candidate_links):
    """Create sample articles using CloudSQL schema."""
    import json
    
    articles = []
    for i in range(50):
        article = Article(
            id=f"article-{i:03d}",                    # NOT "uid"
            candidate_link_id=link.id,                # NOT "source_id"
            wire=json.dumps([...]),                   # NOT "wire_detected" boolean
            status="extracted",
            # ... other fields
        )
        articles.append(article)
        db_session.add(article)
    
    db_session.commit()
    return articles
```

**Key Schema Differences from CSV Era:**

| CSV Schema | CloudSQL Schema | Notes |
|------------|-----------------|-------|
| `Source.name` | `Source.canonical_name` | Display name |
| `Source.domain` | `Source.host` | Domain name |
| - | `Source.host_norm` | Normalized domain |
| `Article.uid` | `Article.id` | Primary key |
| `Article.source_id` | `Article.candidate_link_id` | Foreign key to CandidateLink |
| `Article.wire_detected` (boolean) | `Article.wire` (JSON string) | Wire attribution |
| `Article.county` | Via CandidateLink relationship | No direct field |

## Writing New Tests

### Step 1: Use CloudSQL Schema in Fixtures

When creating test data, always use the actual model fields:

```python
def test_my_endpoint(test_client, db_session, sample_sources):
    # Create additional test data if needed
    from src.models import Article, CandidateLink
    import json
    
    # Create CandidateLink (relationship table)
    link = CandidateLink(
        id="test-link-1",
        url="https://example.com/article",
        source=sample_sources[0].host,
        source_host_id=sample_sources[0].host,
        source_name=sample_sources[0].canonical_name,
        source_county=sample_sources[0].county,
    )
    db_session.add(link)
    db_session.commit()
    
    # Create Article
    article = Article(
        id="test-article-1",                  # Use 'id', not 'uid'
        candidate_link_id=link.id,            # Use 'candidate_link_id', not 'source_id'
        title="Test Article",
        url="https://example.com/article",
        status="extracted",
        wire=json.dumps([{"source": "AP"}]),  # Use JSON, not boolean
    )
    db_session.add(article)
    db_session.commit()
    
    # Make request
    response = test_client.get("/api/my_endpoint")
    assert response.status_code == 200
```

### Step 2: Test Against Endpoint Response

```python
def test_endpoint_returns_correct_data(test_client, sample_articles):
    response = test_client.get("/api/endpoint")
    
    assert response.status_code == 200
    data = response.json()
    
    # The endpoint will query the test database, not production
    assert data["total_articles"] == 50
    assert "wire_count" in data
```

## Common Pitfalls

### ❌ Pitfall 1: Using CSV Schema Fields

```python
# WRONG - uses CSV schema
article = Article(
    uid="article-1",        # Field doesn't exist in CloudSQL!
    source_id=1,            # Should be candidate_link_id
    wire_detected=True,     # Should be wire (JSON)
)
```

### ✅ Solution: Use CloudSQL Schema

```python
# CORRECT - uses CloudSQL schema
article = Article(
    id="article-1",
    candidate_link_id="link-1",
    wire=json.dumps([{"source": "AP"}]),
)
```

### ❌ Pitfall 2: Not Using StaticPool

```python
# WRONG - each thread gets a new in-memory database
engine = create_engine("sqlite:///:memory:")
```

### ✅ Solution: Use StaticPool

```python
# CORRECT - all threads share the same in-memory database
from sqlalchemy.pool import StaticPool

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
```

### ❌ Pitfall 3: Mocking Only get_session()

```python
# WRONG - endpoint might use db_manager.engine directly
monkeypatch.setattr(main.db_manager, "get_session", mock_session)
```

### ✅ Solution: Mock Both Engine and get_session()

```python
# CORRECT - mock engine AND get_session
monkeypatch.setattr(main.db_manager, "engine", db_engine)
monkeypatch.setattr(main.db_manager, "get_session", mock_get_session)
```

## Verifying Schema Correctness

To ensure your test fixtures match the production schema:

1. **Read the model definition:**
   ```bash
   # Check Source model
   grep -A 20 "class Source" src/models/__init__.py
   
   # Check Article model  
   grep -A 50 "class Article" src/models/__init__.py
   ```

2. **Run a quick schema check:**
   ```python
   from src.models import Source, Article
   import inspect
   
   # See all Source fields
   print([col.name for col in Source.__table__.columns])
   
   # See all Article fields
   print([col.name for col in Article.__table__.columns])
   ```

3. **Check for TypeError when creating objects:**
   If you see `TypeError: 'field_name' is an invalid keyword argument for ModelName`, you're using a field that doesn't exist in the CloudSQL schema.

## Running Tests

```bash
# Run single test file
pytest tests/backend/test_ui_overview_endpoint.py -v

# Run all backend tests
pytest tests/backend/ -v

# Run with coverage
pytest tests/backend/ --cov=backend.app --cov-report=html

# Run specific test
pytest tests/backend/test_ui_overview_endpoint.py::test_ui_overview_with_articles -v
```

## Performance Considerations

- In-memory SQLite is **very fast** (< 0.5s for 500 records)
- StaticPool adds minimal overhead
- Each test gets a fresh database (isolated)
- No need for database cleanup between tests

## Integration Testing

For integration tests against actual CloudSQL:

1. Set up Cloud SQL Proxy locally
2. Use a test database (not production!)
3. Replace `db_engine` fixture to use PostgreSQL:

```python
@pytest.fixture(scope="function")
def db_engine():
    """Use actual CloudSQL for integration tests."""
    engine = create_engine(
        "postgresql://user:pass@localhost:5432/test_db"
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
```

## Troubleshooting

### "no such table: articles"

- **Cause:** Endpoint is using production db_manager, not test engine
- **Fix:** Ensure `test_client` fixture properly mocks both `engine` and `get_session()`

### "SQLite objects created in a thread can only be used in that same thread"

- **Cause:** Not using StaticPool or `check_same_thread=False`
- **Fix:** Add `poolclass=StaticPool` and `connect_args={"check_same_thread": False}`

### "TypeError: 'field_name' is an invalid keyword argument"

- **Cause:** Using CSV-era field names instead of CloudSQL schema
- **Fix:** Check model definition and use correct field names

### Test passes but counts are 0

- **Cause:** Fixture data not committed, or endpoint creates new session
- **Fix:** Ensure fixtures call `db_session.commit()` after adding data

## References

- CloudSQL Schema: `src/models/__init__.py`, `src/models/api_backend.py`
- Test Fixtures: `tests/backend/conftest.py`
- Example Tests: `tests/backend/test_ui_overview_endpoint.py`
- DatabaseManager: `src/models/database.py`
