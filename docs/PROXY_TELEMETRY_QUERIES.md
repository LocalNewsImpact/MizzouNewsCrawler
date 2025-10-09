# Proxy Telemetry SQL Queries

Example queries for analyzing proxy performance and patterns in the telemetry database.

## Overview Metrics

### 1. Proxy Usage Summary (Last 7 Days)

```sql
SELECT 
    COUNT(*) as total_requests,
    SUM(CASE WHEN proxy_used = 1 THEN 1 ELSE 0 END) as proxy_requests,
    SUM(CASE WHEN proxy_used = 0 THEN 1 ELSE 0 END) as direct_requests,
    ROUND(100.0 * SUM(CASE WHEN proxy_used = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) as proxy_percentage,
    SUM(CASE WHEN proxy_status = 'success' THEN 1 ELSE 0 END) as proxy_successes,
    SUM(CASE WHEN proxy_status = 'failed' THEN 1 ELSE 0 END) as proxy_failures,
    ROUND(100.0 * SUM(CASE WHEN proxy_status = 'success' THEN 1 ELSE 0 END) / 
          NULLIF(SUM(CASE WHEN proxy_used = 1 THEN 1 ELSE 0 END), 0), 2) as proxy_success_rate
FROM extraction_telemetry_v2
WHERE created_at >= datetime('now', '-7 days');
```

### 2. Daily Proxy Trends

```sql
SELECT 
    DATE(created_at) as date,
    COUNT(*) as total_requests,
    SUM(CASE WHEN proxy_used = 1 THEN 1 ELSE 0 END) as proxy_requests,
    ROUND(100.0 * SUM(CASE WHEN proxy_status = 'success' THEN 1 ELSE 0 END) / 
          NULLIF(SUM(CASE WHEN proxy_used = 1 THEN 1 ELSE 0 END), 0), 2) as success_rate,
    SUM(CASE WHEN proxy_authenticated = 0 AND proxy_used = 1 THEN 1 ELSE 0 END) as missing_auth
FROM extraction_telemetry_v2
WHERE created_at >= datetime('now', '-30 days')
GROUP BY DATE(created_at)
ORDER BY date DESC;
```

## Domain-Specific Analysis

### 3. Top Domains by Proxy Usage

```sql
SELECT 
    host,
    COUNT(*) as total_requests,
    SUM(CASE WHEN proxy_used = 1 THEN 1 ELSE 0 END) as proxy_requests,
    SUM(CASE WHEN proxy_status = 'success' THEN 1 ELSE 0 END) as successes,
    SUM(CASE WHEN proxy_status = 'failed' THEN 1 ELSE 0 END) as failures,
    SUM(CASE WHEN proxy_status = 'bypassed' THEN 1 ELSE 0 END) as bypassed,
    ROUND(100.0 * SUM(CASE WHEN proxy_status = 'success' THEN 1 ELSE 0 END) / 
          NULLIF(SUM(CASE WHEN proxy_used = 1 THEN 1 ELSE 0 END), 0), 2) as success_rate
FROM extraction_telemetry_v2
WHERE created_at >= datetime('now', '-7 days')
  AND proxy_used = 1
GROUP BY host
ORDER BY proxy_requests DESC
LIMIT 20;
```

### 4. Domains with High Proxy Failure Rates

```sql
SELECT 
    host,
    COUNT(*) as proxy_requests,
    SUM(CASE WHEN proxy_status = 'success' THEN 1 ELSE 0 END) as successes,
    SUM(CASE WHEN proxy_status = 'failed' THEN 1 ELSE 0 END) as failures,
    ROUND(100.0 * SUM(CASE WHEN proxy_status = 'failed' THEN 1 ELSE 0 END) / COUNT(*), 2) as failure_rate
FROM extraction_telemetry_v2
WHERE created_at >= datetime('now', '-7 days')
  AND proxy_used = 1
GROUP BY host
HAVING COUNT(*) >= 10  -- Only domains with sufficient requests
  AND failure_rate > 20  -- More than 20% failure rate
ORDER BY failure_rate DESC, proxy_requests DESC
LIMIT 20;
```

### 5. Domains Requiring Proxy (High Bot Detection)

```sql
SELECT 
    host,
    SUM(CASE WHEN proxy_used = 1 AND http_status_code = 403 THEN 1 ELSE 0 END) as proxy_403s,
    SUM(CASE WHEN proxy_used = 0 AND http_status_code = 403 THEN 1 ELSE 0 END) as direct_403s,
    SUM(CASE WHEN proxy_used = 1 THEN 1 ELSE 0 END) as proxy_total,
    SUM(CASE WHEN proxy_used = 0 THEN 1 ELSE 0 END) as direct_total,
    ROUND(100.0 * SUM(CASE WHEN proxy_used = 1 AND http_status_code = 403 THEN 1 ELSE 0 END) / 
          NULLIF(SUM(CASE WHEN proxy_used = 1 THEN 1 ELSE 0 END), 0), 2) as proxy_403_rate,
    ROUND(100.0 * SUM(CASE WHEN proxy_used = 0 AND http_status_code = 403 THEN 1 ELSE 0 END) / 
          NULLIF(SUM(CASE WHEN proxy_used = 0 THEN 1 ELSE 0 END), 0), 2) as direct_403_rate
FROM extraction_telemetry_v2
WHERE created_at >= datetime('now', '-7 days')
  AND http_status_code IN (403, 503)
GROUP BY host
HAVING (proxy_total + direct_total) >= 10
ORDER BY direct_403_rate DESC, direct_total DESC
LIMIT 20;
```

## Error Analysis

### 6. Common Proxy Errors

```sql
SELECT 
    SUBSTR(proxy_error, 1, 100) as error_pattern,
    COUNT(*) as occurrence_count,
    COUNT(DISTINCT host) as affected_domains,
    GROUP_CONCAT(DISTINCT host, ', ') as sample_domains
FROM extraction_telemetry_v2
WHERE proxy_status = 'failed' 
  AND proxy_error IS NOT NULL
  AND created_at >= datetime('now', '-7 days')
GROUP BY SUBSTR(proxy_error, 1, 100)
ORDER BY occurrence_count DESC
LIMIT 15;
```

### 7. ContentDecodingError Domains

```sql
SELECT 
    host,
    COUNT(*) as gzip_errors,
    SUM(CASE WHEN is_success = 1 THEN 1 ELSE 0 END) as eventual_successes,
    MAX(created_at) as last_error
FROM extraction_telemetry_v2
WHERE proxy_error LIKE '%ContentDecodingError%'
  AND created_at >= datetime('now', '-7 days')
GROUP BY host
ORDER BY gzip_errors DESC
LIMIT 20;
```

### 8. Recent Proxy Failures with Details

```sql
SELECT 
    created_at,
    host,
    url,
    http_status_code,
    proxy_url,
    proxy_authenticated,
    SUBSTR(proxy_error, 1, 200) as error_preview
FROM extraction_telemetry_v2
WHERE proxy_status = 'failed'
  AND created_at >= datetime('now', '-24 hours')
ORDER BY created_at DESC
LIMIT 50;
```

## Authentication Analysis

### 9. Authentication Status Over Time

```sql
SELECT 
    DATE(created_at) as date,
    SUM(CASE WHEN proxy_authenticated = 1 THEN 1 ELSE 0 END) as with_auth,
    SUM(CASE WHEN proxy_authenticated = 0 AND proxy_used = 1 THEN 1 ELSE 0 END) as without_auth,
    SUM(CASE WHEN proxy_used = 1 THEN 1 ELSE 0 END) as total_proxy_requests,
    ROUND(100.0 * SUM(CASE WHEN proxy_authenticated = 1 THEN 1 ELSE 0 END) / 
          NULLIF(SUM(CASE WHEN proxy_used = 1 THEN 1 ELSE 0 END), 0), 2) as auth_percentage
FROM extraction_telemetry_v2
WHERE created_at >= datetime('now', '-30 days')
GROUP BY DATE(created_at)
ORDER BY date DESC;
```

### 10. Missing Authentication Impact

```sql
SELECT 
    'With Auth' as auth_status,
    COUNT(*) as requests,
    SUM(CASE WHEN proxy_status = 'success' THEN 1 ELSE 0 END) as successes,
    ROUND(100.0 * SUM(CASE WHEN proxy_status = 'success' THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate
FROM extraction_telemetry_v2
WHERE proxy_used = 1 
  AND proxy_authenticated = 1
  AND created_at >= datetime('now', '-7 days')
UNION ALL
SELECT 
    'Without Auth' as auth_status,
    COUNT(*) as requests,
    SUM(CASE WHEN proxy_status = 'success' THEN 1 ELSE 0 END) as successes,
    ROUND(100.0 * SUM(CASE WHEN proxy_status = 'success' THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate
FROM extraction_telemetry_v2
WHERE proxy_used = 1 
  AND proxy_authenticated = 0
  AND created_at >= datetime('now', '-7 days');
```

## Performance Comparison

### 11. Proxy vs Direct Connection Success Rates

```sql
SELECT 
    CASE 
        WHEN proxy_used = 1 THEN 'Proxy'
        ELSE 'Direct'
    END as connection_type,
    COUNT(*) as total_requests,
    SUM(CASE WHEN is_success = 1 THEN 1 ELSE 0 END) as successful_extractions,
    SUM(CASE WHEN http_status_code = 200 THEN 1 ELSE 0 END) as http_200s,
    SUM(CASE WHEN http_status_code IN (403, 503) THEN 1 ELSE 0 END) as bot_detections,
    ROUND(100.0 * SUM(CASE WHEN is_success = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) as extraction_success_rate,
    ROUND(AVG(total_duration_ms), 2) as avg_duration_ms
FROM extraction_telemetry_v2
WHERE created_at >= datetime('now', '-7 days')
GROUP BY proxy_used
ORDER BY connection_type;
```

### 12. Response Time Comparison by Domain

```sql
SELECT 
    host,
    COUNT(CASE WHEN proxy_used = 1 THEN 1 END) as proxy_requests,
    COUNT(CASE WHEN proxy_used = 0 THEN 1 END) as direct_requests,
    ROUND(AVG(CASE WHEN proxy_used = 1 THEN response_time_ms END), 2) as avg_proxy_time_ms,
    ROUND(AVG(CASE WHEN proxy_used = 0 THEN response_time_ms END), 2) as avg_direct_time_ms,
    ROUND(AVG(CASE WHEN proxy_used = 1 THEN response_time_ms END) - 
          AVG(CASE WHEN proxy_used = 0 THEN response_time_ms END), 2) as proxy_overhead_ms
FROM extraction_telemetry_v2
WHERE created_at >= datetime('now', '-7 days')
  AND response_time_ms IS NOT NULL
  AND response_time_ms > 0
GROUP BY host
HAVING proxy_requests >= 10 AND direct_requests >= 10
ORDER BY ABS(proxy_overhead_ms) DESC
LIMIT 20;
```

## Status Distribution

### 13. Proxy Status Breakdown

```sql
SELECT 
    proxy_status,
    COUNT(*) as count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) as percentage,
    COUNT(DISTINCT host) as unique_hosts
FROM extraction_telemetry_v2
WHERE created_at >= datetime('now', '-7 days')
  AND proxy_status IS NOT NULL
GROUP BY proxy_status
ORDER BY count DESC;
```

### 14. HTTP Status Codes with Proxy Usage

```sql
SELECT 
    http_status_code,
    COUNT(*) as total_occurrences,
    SUM(CASE WHEN proxy_used = 1 THEN 1 ELSE 0 END) as with_proxy,
    SUM(CASE WHEN proxy_used = 0 THEN 1 ELSE 0 END) as without_proxy,
    ROUND(100.0 * SUM(CASE WHEN proxy_used = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) as proxy_percentage
FROM extraction_telemetry_v2
WHERE created_at >= datetime('now', '-7 days')
  AND http_status_code IS NOT NULL
GROUP BY http_status_code
ORDER BY total_occurrences DESC
LIMIT 15;
```

## Extraction Method Correlation

### 15. Proxy Usage by Extraction Method

```sql
SELECT 
    successful_method,
    COUNT(*) as total_extractions,
    SUM(CASE WHEN proxy_used = 1 THEN 1 ELSE 0 END) as with_proxy,
    SUM(CASE WHEN proxy_used = 0 THEN 1 ELSE 0 END) as without_proxy,
    ROUND(100.0 * SUM(CASE WHEN proxy_used = 1 AND is_success = 1 THEN 1 ELSE 0 END) / 
          NULLIF(SUM(CASE WHEN proxy_used = 1 THEN 1 ELSE 0 END), 0), 2) as proxy_success_rate,
    ROUND(100.0 * SUM(CASE WHEN proxy_used = 0 AND is_success = 1 THEN 1 ELSE 0 END) / 
          NULLIF(SUM(CASE WHEN proxy_used = 0 THEN 1 ELSE 0 END), 0), 2) as direct_success_rate
FROM extraction_telemetry_v2
WHERE created_at >= datetime('now', '-7 days')
  AND successful_method IS NOT NULL
GROUP BY successful_method
ORDER BY total_extractions DESC;
```

## Alerting Queries

### 16. Recent Authentication Issues (Alert)

```sql
SELECT 
    COUNT(*) as missing_auth_requests,
    COUNT(DISTINCT host) as affected_domains
FROM extraction_telemetry_v2
WHERE proxy_used = 1 
  AND proxy_authenticated = 0
  AND created_at >= datetime('now', '-1 hour');
-- Alert if missing_auth_requests > 10
```

### 17. Sudden Proxy Failure Spike (Alert)

```sql
WITH recent AS (
    SELECT 
        ROUND(100.0 * SUM(CASE WHEN proxy_status = 'failed' THEN 1 ELSE 0 END) / 
              NULLIF(SUM(CASE WHEN proxy_used = 1 THEN 1 ELSE 0 END), 0), 2) as failure_rate
    FROM extraction_telemetry_v2
    WHERE created_at >= datetime('now', '-1 hour')
),
baseline AS (
    SELECT 
        ROUND(100.0 * SUM(CASE WHEN proxy_status = 'failed' THEN 1 ELSE 0 END) / 
              NULLIF(SUM(CASE WHEN proxy_used = 1 THEN 1 ELSE 0 END), 0), 2) as failure_rate
    FROM extraction_telemetry_v2
    WHERE created_at >= datetime('now', '-7 days')
      AND created_at < datetime('now', '-1 hour')
)
SELECT 
    recent.failure_rate as current_failure_rate,
    baseline.failure_rate as baseline_failure_rate,
    recent.failure_rate - baseline.failure_rate as spike
FROM recent, baseline;
-- Alert if spike > 10
```

## Usage Notes

### SQLite Date Functions

These queries use SQLite date functions. For PostgreSQL (Cloud SQL), replace:
- `datetime('now', '-7 days')` with `NOW() - INTERVAL '7 days'`
- `DATE(created_at)` with `created_at::DATE`
- `GROUP_CONCAT` with `STRING_AGG`

### Dashboard Integration

These queries are designed for:
1. **Grafana**: Use as SQL data sources
2. **FastAPI endpoints**: Wrap in Python functions
3. **Scheduled reports**: Run via cron or scheduled tasks
4. **Alerting systems**: Use alerting queries (#16, #17) with thresholds

### Performance Tips

- Add indexes for frequently queried columns:
  ```sql
  CREATE INDEX idx_proxy_usage ON extraction_telemetry_v2(proxy_used, created_at);
  CREATE INDEX idx_proxy_status ON extraction_telemetry_v2(proxy_status, created_at);
  CREATE INDEX idx_host_proxy ON extraction_telemetry_v2(host, proxy_used, created_at);
  ```

- Use `EXPLAIN QUERY PLAN` to optimize slow queries
- Consider materialized views for frequently-run aggregations
