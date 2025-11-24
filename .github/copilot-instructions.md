# GitHub Copilot Instructions

## Database Query Protocol

### Production Database Access (PostgreSQL via Cloud SQL)

**URGENT: ALWAYS use `kubectl exec` to query production data. The local environment DOES NOT connect to production.**

To query the production database, you must execute the Python script inside a running pod (API or Processor) in the `production` namespace.

```bash
# Standard query pattern (USE THIS):
kubectl exec -n production deployment/mizzou-api -- python -c "
from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
with db.get_session() as session:
    result = session.execute(text('YOUR SQL HERE')).fetchall()
    for row in result:
        print(row)
"
```

**Common queries:**

```python
# Check unextracted articles for a source
result = session.execute(text('''
    SELECT COUNT(*) FROM candidate_links 
    WHERE source = 'example.com' 
    AND status = 'article'
    AND id NOT IN (SELECT candidate_link_id FROM articles WHERE candidate_link_id IS NOT NULL)
''')).scalar()

# Table counts
result = session.execute(text('''
    SELECT 
        (SELECT COUNT(*) FROM candidate_links) as candidates,
        (SELECT COUNT(*) FROM articles) as articles,
        (SELECT COUNT(*) FROM sources) as sources
''')).fetchone()

# Recent articles by source (last 24h)
results = session.execute(text('''
    SELECT cl.source, COUNT(*) as cnt
    FROM articles a
    JOIN candidate_links cl ON a.candidate_link_id = cl.id
    WHERE a.extracted_at >= NOW() - INTERVAL '24 hours'
    GROUP BY cl.source ORDER BY cnt DESC LIMIT 10
''')).fetchall()
```

**Key Schema Reference:**

- `candidate_links`: Discovered URLs (id, url, source, status, discovered_at, candidate_link_id FK)
- `articles`: Extracted content (id, candidate_link_id FK, url, title, author, text, extracted_at)
- `sources`: Publishers (id, host, canonical_name, city, county, status)
- `article_entities`: NER results (article_id FK, entity_text, entity_type, extractor_version)
- `article_labels`: ML classifications (article_id FK, label, confidence, label_version)

**NEVER:**
- **NEVER** assume the local `venv` connects to the production database. It connects to a local SQLite or empty Postgres instance.
- **NEVER** run queries locally expecting production results.
- Don't forget `text()` wrapper for raw SQL in SQLAlchemy

## Test Development Protocol

When creating new test coverage (unit, integration, or postgres tests), follow this mandatory pre-implementation checklist:

### 1. Database Schema Analysis
- **Grep for model definitions**: Find the SQLAlchemy model class(es) being tested
- **Identify ALL constraints**:
  - NOT NULL columns that require values
  - Foreign key relationships and their target tables
  - Unique constraints that could cause collisions
  - Default values and their behavior
- **Check dependent models**: If creating objects with FKs, understand the parent table requirements

### 2. Production Code Analysis
- **Find real usage**: Locate where the function/method is called in production code
- **Match parameter signatures exactly**:
  - Parameter order (positional vs keyword)
  - Required vs optional parameters
  - Default values and their types
- **Understand data flow**: What values does production code pass? What transformations occur?

### 3. Test Infrastructure Analysis
- **Identify relevant fixtures**:
  - `cloud_sql_session`: PostgreSQL integration tests with automatic rollback
  - Database engines and their configuration
  - Mocking utilities and their behavior
- **Understand cleanup behavior**:
  - Does the fixture handle rollback automatically?
  - Are there unique constraints that require unique test data?
  - Do tests need explicit cleanup code?

### 4. CI/CD Configuration
- **Determine test execution environment**:
  - **Integration tests run in Docker** (uses PostgreSQL 15 container)
  - `postgres-integration` job: Has PostgreSQL 15 service, runs `-m integration`
  - `integration` job: Uses SQLite in-memory, runs default tests (excludes `-m "not integration"`)
  - Unit tests: Fast, no database dependencies
  - **Local integration testing**: Use `./scripts/test-local.sh` or similar Docker-based test runner
- **Apply correct pytest markers**:
  - `@pytest.mark.postgres`: Requires PostgreSQL-specific features (FOR UPDATE SKIP LOCKED, etc.)
  - `@pytest.mark.integration`: Runs in postgres-integration job, excluded from SQLite job
  - `@pytest.mark.parallel`: Custom marker for parallel processing tests
  - `@pytest.mark.slow`: For tests that take >5 seconds
- **Test marker rules**:
  - If test uses PostgreSQL-specific syntax → needs both `@pytest.mark.postgres` AND `@pytest.mark.integration`
  - If test uses cloud_sql_session fixture → needs `@pytest.mark.integration`
  - SQLite tests should NOT be marked with `integration` (they run in default job)

### 5. Test Isolation & Data Management
- **Session management**:
  - Understand which session to use (fixture vs creating new sessions)
  - Know when transactions commit vs rollback
  - Handle connection cleanup in finally blocks
- **Unique data generation**:
  - Use timestamps for unique URLs/identifiers if needed
  - Understand if test data persists across test runs
  - Check for potential race conditions in parallel test execution

### 6. Pre-Implementation Checklist
Before writing ANY test code, create a checklist of ALL potential failure points:
- [ ] Missing foreign key dependencies
- [ ] Wrong parameter order or types
- [ ] Missing required NOT NULL fields
- [ ] Incorrect test markers for CI job routing
- [ ] Unique constraint violations
- [ ] Session/transaction isolation issues
- [ ] PostgreSQL vs SQLite compatibility
- [ ] Connection cleanup and resource leaks
- [ ] Test data cleanup (if not automatic)

### 7. Implementation Approach
**Present analysis FIRST, then implement:**
1. Show your discovery findings (schema, production usage, fixtures, CI config)
2. List all identified failure points
3. Propose test structure addressing each issue
4. **Wait for approval before writing test code**
5. Implement tests with all issues addressed upfront

### Example Workflow

**Good Request:**
```
User: "Write tests for the new parallel entity extraction feature"

Copilot Response:
"Let me analyze the requirements first:

1. Database Schema Analysis:
   - Article model (src/models/__init__.py lines 128-165):
     * candidate_link_id: ForeignKey, NOT NULL, required
     * text, content: Required for entity extraction
   - CandidateLink model: Required parent table
     * url: NOT NULL, UNIQUE
     * source: NOT NULL

2. Production Usage:
   - src/cli/commands/entity_extraction.py line 202:
     * Calls save_article_entities(session, article_id, entities, extractor_version, text_hash, autocommit=False)
     * Note: text_hash is 5th positional parameter

3. Test Infrastructure:
   - cloud_sql_session fixture (tests/backend/conftest.py line 387):
     * Provides PostgreSQL session with automatic rollback cleanup
     * No need for explicit test data deletion
   - Requires @pytest.mark.integration to run in postgres-integration job

4. CI Configuration:
   - postgres-integration job: Has PostgreSQL 15, runs `-m integration`
   - integration job: SQLite only, will fail on FOR UPDATE SKIP LOCKED
   - Need both @pytest.mark.postgres AND @pytest.mark.integration

5. Potential Failure Points:
   [ ] Missing candidate_link_id in Article creation
   [ ] Wrong parameter order for save_article_entities (text_hash missing)
   [ ] Missing @pytest.mark.integration (would run in SQLite job and hang)
   [ ] Unique constraint violation on CandidateLink.url
   [ ] Session isolation issues with multiple sessions

Proposed test structure:
- Create CandidateLink first with unique URL
- Create Article with candidate_link_id reference
- Call save_article_entities with all 6 parameters (including text_hash)
- Use cloud_sql_session fixture (handles cleanup)
- Mark with @pytest.mark.postgres AND @pytest.mark.integration

Shall I proceed with implementation?"
```

**Bad Request (what NOT to do):**
```
User: "Write tests for the new parallel entity extraction feature"

Copilot Response: [immediately writes test code without analysis]
↓
Result: Missing candidate_link_id, test fails in CI
↓
Result: Missing @pytest.mark.integration, test hangs in SQLite job
↓
Result: Multiple CI failures, wasted time
```

## Key Principles

1. **Discovery before implementation**: Understand the full context before writing code
2. **Match production exactly**: Test code should mirror production usage patterns
3. **Consider the CI environment**: Tests must work in the actual CI job configuration
4. **Anticipate failures**: Think through all potential issues before first attempt
5. **Get approval first**: Present analysis and approach, wait for confirmation