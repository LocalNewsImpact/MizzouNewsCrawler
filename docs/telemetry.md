# Telemetry System Documentation

## Overview

The MizzouNewsCrawler telemetry system tracks discovery method effectiveness, HTTP request outcomes, and site failures to enable data-driven optimization of the crawling pipeline. This document describes the telemetry schema, how to inspect and query telemetry data, and common troubleshooting steps.

## Key Components

### 1. Discovery Method Effectiveness Tracking

The telemetry system records how well each discovery method (RSS, newspaper4k, storysniffer) performs for each source. This data helps the discovery pipeline prioritize effective methods and skip ineffective ones.

**Database Table:** `discovery_method_effectiveness`

**Columns:**
- `id`: Primary key
- `source_id`: Foreign key to sources table
- `source_url`: URL of the news source
- `discovery_method`: One of `rss_feed`, `newspaper4k`, or `storysniffer`
- `status`: Discovery outcome (`success`, `no_feed`, `timeout`, `connection_error`, `parse_error`, `blocked`, `server_error`, `skipped`)
- `articles_found`: Number of articles discovered in the last attempt
- `success_rate`: Rolling average success rate (0-100)
- `last_attempt`: Timestamp of the most recent attempt
- `attempt_count`: Total number of attempts for this source/method combination
- `avg_response_time_ms`: Average response time in milliseconds
- `last_status_codes`: JSON array of recent HTTP status codes
- `notes`: Optional notes about the discovery attempt
- `created_at`: Record creation timestamp
- `updated_at`: Last update timestamp

### 2. HTTP Status Tracking

Tracks HTTP requests made during discovery, including status codes, response times, and errors.

**Database Table:** `http_status_tracking`

**Columns:**
- `id`: Primary key
- `source_id`: Foreign key to sources table
- `source_url`: Base URL of the news source
- `discovery_method`: Discovery method that made the request
- `attempted_url`: Specific URL that was requested (e.g., RSS feed URL)
- `status_code`: HTTP status code (200, 404, 500, etc.) or 0 for connection errors
- `status_category`: Categorized status (`2xx`, `3xx`, `4xx`, `5xx`)
- `response_time_ms`: Response time in milliseconds
- `timestamp`: When the request was made
- `operation_id`: ID of the discovery operation
- `error_message`: Error details if the request failed
- `content_length`: Size of the response body in bytes

### 3. Discovery Outcomes

Records the overall outcome of discovery attempts per source.

**Database Table:** `discovery_outcomes`

**Columns:**
- `id`: Primary key
- `source_id`: Foreign key to sources table
- `operation_id`: ID of the discovery operation
- `outcome`: Overall outcome (`success`, `partial_success`, `failure`)
- `articles_found`: Total number of articles discovered
- `methods_attempted`: JSON array of methods tried
- `timestamp`: When the discovery was performed
- `duration_ms`: How long discovery took
- `notes`: Additional context

## RSS Failure Tracking in Source Metadata

In addition to telemetry tables, the `sources.metadata` JSONB column tracks RSS-specific failure state:

**Metadata Fields:**
- `rss_missing`: ISO timestamp when RSS was marked as permanently unavailable (set after `RSS_MISSING_THRESHOLD` consecutive non-network failures, default 3, OR `RSS_TRANSIENT_THRESHOLD` repeated transient errors, default 5 in 7 days)
- `rss_consecutive_failures`: Counter of consecutive non-network RSS failures
- `rss_transient_failures`: Array of transient error records with timestamps (rolling 7-day window)
- `rss_last_failed`: ISO timestamp of the most recent RSS network error (timeout, connection refused, etc.)
- `last_successful_method`: The discovery method that last successfully found articles

**How It Works:**

1. **Non-Network Failures:** When RSS discovery tries all candidate feeds and finds no valid RSS (404, parse errors), `rss_consecutive_failures` increments. After reaching `RSS_MISSING_THRESHOLD`, `rss_missing` is set to the current timestamp.

2. **Transient Errors (NEW):** Repeated "transient" errors (429, 403, 5xx) are now tracked over time in `rss_transient_failures`. Each failure records a timestamp and status code. If a source exceeds `RSS_TRANSIENT_THRESHOLD` (default 5) transient failures within `RSS_TRANSIENT_WINDOW_DAYS` (default 7 days), it's marked as permanently blocked (`rss_missing` is set). This prevents wasting resources on feeds that repeatedly return transient errors that are actually permanent blocks misreported by the server.

3. **Network Errors (Legacy):** Pure network errors (timeouts, connection refused) set `rss_last_failed` timestamp but don't count toward either consecutive or transient thresholds.

4. **Success:** When RSS successfully discovers articles, `_update_source_meta()` is called with `last_successful_method: "rss_feed"`, `rss_missing: null`, `rss_last_failed: null`, `rss_consecutive_failures: 0`, and `rss_transient_failures: []`, fully resetting all failure state.

5. **Retry Windows:** If `rss_missing` is set, the discovery pipeline skips RSS for that source for a configurable window (default 30 days). After the window expires, RSS is re-attempted, allowing recovery if the site adds an RSS feed later.

## Querying Telemetry Data

### Check Discovery Effectiveness for a Source

```sql
SELECT 
    discovery_method,
    status,
    articles_found,
    success_rate,
    attempt_count,
    avg_response_time_ms,
    last_attempt
FROM discovery_method_effectiveness
WHERE source_id = 'YOUR_SOURCE_ID'
ORDER BY success_rate DESC, articles_found DESC;
```

### Find Sources with No Historical Data

```sql
SELECT s.id, s.canonical_name, s.url
FROM sources s
LEFT JOIN discovery_method_effectiveness dme ON s.id = dme.source_id
WHERE dme.id IS NULL
ORDER BY s.canonical_name;
```

### Check HTTP Request Patterns

```sql
SELECT 
    source_url,
    discovery_method,
    status_code,
    COUNT(*) as request_count,
    AVG(response_time_ms) as avg_response_ms
FROM http_status_tracking
WHERE source_id = 'YOUR_SOURCE_ID'
GROUP BY source_url, discovery_method, status_code
ORDER BY request_count DESC;
```

### Find Sources with RSS Marked as Missing

```sql
SELECT 
    id,
    canonical_name,
    url,
    metadata->>'rss_missing' as rss_missing_since,
    metadata->>'rss_consecutive_failures' as failure_count
FROM sources
WHERE metadata->>'rss_missing' IS NOT NULL
ORDER BY metadata->>'rss_missing' DESC
LIMIT 50;
```

### Check Discovery Outcomes Over Time

```sql
SELECT 
    DATE(timestamp) as date,
    outcome,
    COUNT(*) as outcome_count,
    AVG(articles_found) as avg_articles,
    AVG(duration_ms) as avg_duration_ms
FROM discovery_outcomes
WHERE timestamp > NOW() - INTERVAL '7 days'
GROUP BY DATE(timestamp), outcome
ORDER BY date DESC, outcome;
```

## Using has_historical_data() in Code

The `OperationTracker.has_historical_data(source_id)` method checks if any telemetry data exists for a source:

```python
from src.utils.telemetry import create_telemetry_system

telemetry = create_telemetry_system()
if telemetry.has_historical_data("source-123"):
    # Use historical data to prioritize methods
    effective_methods = telemetry.get_effective_discovery_methods("source-123")
else:
    # No history, try all methods
    effective_methods = [DiscoveryMethod.RSS_FEED, DiscoveryMethod.NEWSPAPER4K]
```

This is used in `SourceProcessor._determine_effective_methods()` to decide which discovery methods to attempt.

## Telemetry Configuration

### Database URL

Telemetry uses the same database as the main application by default. You can override it with:

```bash
export TELEMETRY_DATABASE_URL="postgresql://user:pass@host/db"
```

### Cloud SQL Connector

If using Google Cloud SQL, set:

```bash
export USE_CLOUD_SQL_CONNECTOR=true
export CLOUD_SQL_INSTANCE="project:region:instance"
export DATABASE_USER="myuser"
export DATABASE_PASSWORD="mypass"
export DATABASE_NAME="mizzou"
```

### Async vs Sync Writes

By default, telemetry writes are asynchronous (background thread). For testing, you can use synchronous writes:

```python
from src.telemetry.store import TelemetryStore

store = TelemetryStore(database_url, async_writes=False)
```

## Running Telemetry Migrations

Telemetry tables are created automatically on first use via `_ensure_base_schema()` in `src/utils/telemetry.py`. However, for production deployments, it's recommended to use Alembic migrations:

1. Generate a migration (if schema changes):
   ```bash
   alembic revision --autogenerate -m "Add telemetry tables"
   ```

2. Review the generated migration in `alembic/versions/`

3. Apply the migration:
   ```bash
   alembic upgrade head
   ```

4. For Cloud environments, migrations are applied automatically via the CI/CD pipeline before deploying new service versions.

### Manual Schema Creation (Development Only)

If you need to manually create telemetry tables:

```sql
-- See src/utils/telemetry.py: _DISCOVERY_METHOD_SCHEMA, _HTTP_STATUS_SCHEMA, _DISCOVERY_OUTCOMES_SCHEMA
-- These DDL statements are executed automatically on first use
```

## Troubleshooting

### "No historical data" Messages in Logs

**Symptom:** Discovery logs show "No historical data available for source X, using all methods"

**Causes:**
1. First-time discovery for that source (expected)
2. Telemetry writes are failing silently
3. Telemetry tables don't exist

**Debugging:**
1. Check if telemetry tables exist:
   ```sql
   SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%telemetry%' OR name LIKE '%discovery%';
   ```

2. Check for telemetry write errors in application logs:
   ```bash
   grep -i "telemetry" logs/crawler.log | grep -i "error\|fail"
   ```

3. Manually test telemetry writes:
   ```python
   from src.utils.telemetry import create_telemetry_system
   from src.utils.telemetry import DiscoveryMethod, DiscoveryMethodStatus

   telemetry = create_telemetry_system()
   telemetry.update_discovery_method_effectiveness(
       source_id="test-source",
       source_url="https://example.com",
       discovery_method=DiscoveryMethod.RSS_FEED,
       status=DiscoveryMethodStatus.SUCCESS,
       articles_found=5,
       response_time_ms=250,
       status_codes=[200],
   )
   telemetry._store.flush()  # Force synchronous write
   ```

4. Check if data was written:
   ```sql
   SELECT * FROM discovery_method_effectiveness WHERE source_id = 'test-source';
   ```

### RSS Not Being Skipped Despite rss_missing Being Set

**Symptom:** Discovery still attempts RSS for sources with `rss_missing` set

**Causes:**
1. Retry window has expired (default 30 days)
2. `_should_skip_rss()` logic not working

**Debugging:**
1. Check source metadata:
   ```sql
   SELECT metadata FROM sources WHERE id = 'YOUR_SOURCE_ID';
   ```

2. Verify retry window logic in `source_processing.py`:
   ```python
   # _should_skip_rss() respects RSS_RETRY_WINDOW_DAYS
   ```

3. Check if `rss_missing` timestamp is recent:
   ```sql
   SELECT 
       id, 
       metadata->>'rss_missing' as rss_missing,
       NOW() - (metadata->>'rss_missing')::timestamp as age
   FROM sources
   WHERE metadata->>'rss_missing' IS NOT NULL;
   ```

### Telemetry Write Performance Issues

**Symptom:** Discovery is slow, telemetry queue is growing

**Causes:**
1. Database connection issues
2. Too many concurrent writes
3. Lock contention on telemetry tables

**Debugging:**
1. Check telemetry queue size (not directly exposed, monitor logs for "queue" warnings)

2. Monitor database connections:
   ```sql
   SELECT * FROM pg_stat_activity WHERE datname = 'mizzou';
   ```

3. Check for lock contention:
   ```sql
   SELECT * FROM pg_locks WHERE granted = false;
   ```

**Solutions:**
- Increase database connection pool size
- Use NullPool for async writes (already configured)
- Reduce telemetry write frequency (batch updates)

### Telemetry Data Not Appearing After Updates

**Symptom:** Code changes to update telemetry, but data doesn't appear

**Causes:**
1. Exception swallowed silently
2. Async writes not flushed before shutdown
3. Database transaction not committed

**Debugging:**
1. Check for new logging added in this PR:
   ```bash
   grep "Failed to update.*telemetry\|Failed to record.*telemetry" logs/crawler.log
   ```

2. Ensure flush is called before shutdown:
   ```python
   telemetry._store.flush()
   telemetry._store.shutdown(wait=True)
   ```

3. For tests, use synchronous writes:
   ```python
   store = TelemetryStore(database_url, async_writes=False)
   ```

## Best Practices

1. **Always log telemetry failures:** Use `logger.warning()` or `logger.error()` when telemetry writes fail, don't silently swallow exceptions.

2. **Flush before critical operations:** Call `telemetry._store.flush()` before querying recently-written data or shutting down.

3. **Use appropriate markers for tests:** Mark telemetry integration tests with `@pytest.mark.integration` so they run in the appropriate CI job.

4. **Monitor telemetry health:** Regularly check `discovery_method_effectiveness` and `discovery_outcomes` tables to ensure data is being written.

5. **Respect retry windows:** Don't mark sources as permanently failed too quickly. Use network error thresholds and retry windows to handle transient issues.

## Related Files

- `src/utils/telemetry.py` - Core telemetry system and OperationTracker
- `src/telemetry/store.py` - TelemetryStore for database persistence
- `src/crawler/discovery.py` - Discovery methods with telemetry calls
- `src/crawler/source_processing.py` - Source processing with metadata updates
- `tests/test_rss_telemetry_integration.py` - Telemetry integration tests
- `tests/test_telemetry_*.py` - Additional telemetry tests

## See Also

- [Discovery Pipeline Documentation](./discovery.md)
- [Database Schema Documentation](./database.md)
- [Testing Guide](../tests/README.md)
