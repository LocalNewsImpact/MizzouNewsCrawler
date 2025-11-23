# Test Coverage Summary for Database-Driven Wire Detection

## Overview

This document summarizes test coverage for the new database-driven wire service and broadcaster detection functionality added on branch `fix/github-action-service-detection`.

## Changes Requiring Test Coverage

### 1. New Database Tables
- `wire_services`: 31 wire service patterns (AP, Reuters, AFP, etc.)
- `local_broadcaster_callsigns`: 5 Missouri market broadcasters (KMIZ, KOMU, KRCG, KQFX, KJLU)

### 2. New Methods in ContentTypeDetector
- `_get_wire_service_patterns()`: Load patterns from database with 5-minute caching
- `_get_local_broadcaster_callsigns(dataset="missouri")`: Load callsigns from database with 5-minute caching

### 3. New Detection Logic
- URL matching for broadcaster content (own site vs syndicated)
- Domain mapping fallback (_CALLSIGN_DOMAINS dict)
- Generic "Broadcaster" pattern with URL validation

## Existing Test Coverage

### tests/utils/test_wire_service_detection.py (424 lines)
**Coverage:**
- AFP dateline detection (Paris, London, Washington patterns)
- AP dateline and byline patterns (staff, AP News Service, etc.)
- Reuters dateline patterns (various cities)
- Wire service attribution in content
- Multiple wire indicators combining

**What's NOT covered:**
- Database query functions (_get_wire_service_patterns)
- Cache behavior (5-minute TTL)
- Broadcaster URL matching logic
- Domain mapping fallback
- Database unavailability fallback

### tests/utils/test_content_type_detector.py (155 lines)
**Coverage:**
- Obituary detection (title, URL, content patterns)
- Opinion detection (title prefix, URL segment)

**What's NOT covered:**
- Database-driven wire detection
- Broadcaster callsign detection
- URL matching logic

## Test Implementation Strategy

Given the project's testing philosophy and CI configuration:

### Integration Tests (@pytest.mark.integration @pytest.mark.postgres)
These require production database access and run in the `postgres-integration` CI job:

1. **End-to-end detection tests** (already exist in test_wire_service_detection.py):
   - Wire service dateline detection (AP, Reuters, AFP) ✅
   - Wire service byline detection ✅
   - Multiple evidence sources combining ✅

2. **Production verification tests** (manual, not CI):
   - Test against actual production database
   - Verify 31 patterns loaded correctly
   - Verify 5 broadcaster callsigns loaded correctly

### Unit Tests (no database required)
These run in default CI job with SQLite:

1. **Caching behavior** (mock database):
   - Cache TTL expiry after 5 minutes
   - Cache hits vs misses
   - Multiple calls use cached data

2. **URL matching logic** (mock database):
   - KMIZ on abc17news.com → not wire (own site)
   - KMIZ on komu.com → wire (syndicated)
   - Domain mapping fallback (_CALLSIGN_DOMAINS)
   - Unknown broadcaster handling (WGBH)

3. **Fallback behavior** (no database):
   - Empty patterns list when database unavailable
   - Empty callsigns set when database unavailable
   - Detection continues without errors

## Test Files

### tests/utils/test_database_driven_wire_detection.py
**Purpose:** Unit tests for new database-driven functionality with mocked database responses

**Test Classes:**
1. `TestDatabaseDrivenWirePatterns`: Wire pattern loading and caching
2. `TestLocalBroadcasterCallsigns`: Broadcaster callsign loading and caching
3. `TestDetectorVersionTracking`: Version tracking for database changes
4. `TestDatabaseFallbackBehavior`: Graceful fallback when database unavailable
5. `TestIntegrationWithExistingWireDetection`: Ensure existing detection still works

**Approach:**
- Mock database responses using fixtures
- Test caching behavior with time simulation
- Test URL matching logic with various scenarios
- Test fallback behavior without database

## Production Verification (Manual)

Since integration tests can't easily inject test data into production database, use manual verification:

```python
# Run from local environment with production database access
python -c "
from src.models.database import DatabaseManager
from src.utils.content_type_detector import ContentTypeDetector
from sqlalchemy import text

# Verify database tables populated
db = DatabaseManager()
with db.get_session() as session:
    ws_count = session.execute(text('SELECT COUNT(*) FROM wire_services WHERE active = true')).scalar()
    print(f'Wire services: {ws_count} (expected 31)')
    
    lbc_count = session.execute(text(\"SELECT COUNT(*) FROM local_broadcaster_callsigns WHERE dataset = 'missouri'\")).scalar()
    print(f'Broadcaster callsigns: {lbc_count} (expected 5)')

# Test detection
detector = ContentTypeDetector()

# Test 1: KMIZ on own site (not wire)
result1 = detector.detect(
    url='https://abc17news.com/story',
    title='Local News',
    metadata={},
    content='COLUMBIA, Mo. (KMIZ) — Local content...'
)
print(f'KMIZ on abc17news.com: {result1.status if result1 else \"None\"} (expected None)')

# Test 2: KMIZ on different site (wire/syndicated)
result2 = detector.detect(
    url='https://komu.com/story',
    title='Local News',
    metadata={},
    content='COLUMBIA, Mo. (KMIZ) — Local content...'
)
print(f'KMIZ on komu.com: {result2.status if result2 else \"None\"} (expected wire)')

# Test 3: AP (wire service)
result3 = detector.detect(
    url='https://example.com/story',
    title='National News',
    metadata={},
    content='WASHINGTON (AP) — National news...'
)
print(f'AP dateline: {result3.status if result3 else \"None\"} (expected wire)')
"
```

## Coverage Gaps & Future Work

### High Priority
- [ ] Mock-based unit tests for _get_wire_service_patterns() with caching
- [ ] Mock-based unit tests for _get_local_broadcaster_callsigns() with caching
- [ ] URL matching logic tests for broadcaster syndication detection

### Medium Priority
- [ ] Performance tests for database query caching effectiveness
- [ ] Error handling tests for database connection failures
- [ ] Tests for cache invalidation after TTL expiry

### Low Priority
- [ ] Integration tests with actual PostgreSQL test database
- [ ] Load tests for concurrent detector instances with shared cache
- [ ] Tests for dataset parameter filtering in _get_local_broadcaster_callsigns()

## CI Configuration Notes

**postgres-integration job** (`.github/workflows/test.yml`):
- Has PostgreSQL 15 service
- Runs tests with `-m integration`
- Can use `FOR UPDATE SKIP LOCKED` and other PostgreSQL-specific features

**integration job** (`.github/workflows/test.yml`):
- Uses SQLite in-memory database
- Runs default tests (excludes `-m "not integration"`)
- Cannot run PostgreSQL-specific queries

**Test Markers:**
- `@pytest.mark.postgres`: Requires PostgreSQL-specific features
- `@pytest.mark.integration`: Runs in postgres-integration job
- Both markers should be applied to tests that need PostgreSQL

## Recommendations

1. **Keep existing wire detection tests unchanged** - They provide good coverage for dateline/byline patterns
2. **Add focused unit tests for new methods** - Mock database responses to test caching and URL matching
3. **Use manual production verification** - Confirm 31 patterns and 5 callsigns work correctly
4. **Document testing approach** - Help future contributors understand testing strategy

## References

- Copilot Instructions: `.github/copilot-instructions.md` (Test Development Protocol section)
- Existing Tests: `tests/utils/test_wire_service_detection.py`
- Production Database: Cloud SQL PostgreSQL (31 patterns, 5 callsigns confirmed)
- Version: ContentTypeDetector v2025-11-23b (database-driven)
