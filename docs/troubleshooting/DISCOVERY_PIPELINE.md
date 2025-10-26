# Discovery Pipeline Troubleshooting Guide

**Last Updated**: October 21, 2025  
**Version**: 2.0

---

## Quick Diagnostics

### Step 1: Check Pipeline Status

```bash
python -m src.cli discovery-status
```

This shows:
- Available datasets
- Source counts and discovery status
- Sources due for discovery
- Recent activity

### Step 2: Run Validation

```bash
python scripts/validate_discovery_setup.py [dataset_label]
```

Examples:
```bash
# Validate entire system
python scripts/validate_discovery_setup.py

# Validate specific dataset
python scripts/validate_discovery_setup.py Mizzou-Missouri-State
```

---

## Common Issues and Solutions

### Issue 1: "Processing 0 sources"

**Symptoms**:
```
Sources available: 10
Sources due for discovery: 0
Sources skipped (not due): 10
Sources to process: 0
```

**Cause**: Default `--due-only` scheduling behavior filters out sources not yet due.

**Solutions**:

#### Option A: Override Scheduling (First Run)
```bash
python -m src.cli discover-urls --force-all
```

#### Option B: Run Without Scheduling
```bash
# New default behavior (no --due-only)
python -m src.cli discover-urls
```

#### Option C: Use Scheduling (Production)
```bash
# Explicitly enable scheduling
python -m src.cli discover-urls --due-only
```

---

### Issue 2: "Dataset 'X' not found"

**Symptoms**:
```
❌ Dataset 'Mizzou-Missouri-State' not found in database
Available datasets: dataset1, dataset2
```

**Cause**: Dataset label doesn't exist or is misspelled.

**Solutions**:

#### Option A: List Available Datasets
```bash
python -m src.cli discovery-status
```

#### Option B: Check Database Directly
```bash
sqlite3 data/mizzou.db "SELECT label, slug FROM datasets ORDER BY label;"
```

#### Option C: Create/Load Dataset
```bash
# Load sources which creates dataset if needed
python -m src.cli load-sources --csv sources/publinks.csv
```

---

### Issue 3: "Dataset has no linked sources"

**Symptoms**:
```
⚠️ Dataset 'MyDataset' has no linked sources
```

**Cause**: Dataset exists but no sources are linked to it.

**Solutions**:

#### Check Dataset-Source Links
```sql
-- Run in sqlite3 data/mizzou.db
SELECT 
    d.label as dataset,
    COUNT(ds.source_id) as source_count
FROM datasets d
LEFT JOIN dataset_sources ds ON d.id = ds.dataset_id
GROUP BY d.id
ORDER BY source_count DESC;
```

#### Re-load Sources
```bash
python -m src.cli load-sources --csv sources/publinks.csv
```

---

### Issue 4: Database Compatibility Errors

**Symptoms**:
```
OperationalError: near "DISTINCT": syntax error
```

**Cause**: PostgreSQL-specific SQL on SQLite database.

**Solution**: Ensure you're using the latest version with database compatibility fixes.

```bash
# Verify database dialect is detected
python -c "
from src.models.database import DatabaseManager
db = DatabaseManager('sqlite:///data/mizzou.db')
print(f'Dialect: {db.engine.dialect.name}')
"
```

**Expected Output**:
```
Dialect: sqlite
```

If issues persist, check that `get_sources_to_process()` uses dialect-specific queries.

---

### Issue 5: No Candidate URLs Discovered

**Symptoms**:
```
Sources processed: 5
Total candidate URLs discovered: 0
```

**Causes**:
1. Sources have no RSS feeds
2. Network/proxy issues
3. Sites blocking crawler
4. Sites have no recent articles

**Diagnostics**:

#### Check Individual Source
```bash
# Run discovery for single source with debug logging
python -m src.cli discover-urls \
    --source "Sikeston Standard Democrat" \
    --log-level DEBUG
```

#### Review Telemetry
```sql
-- Check discovery method effectiveness
SELECT 
    source_url,
    discovery_method,
    status,
    articles_found,
    notes
FROM discovery_method_effectiveness
WHERE created_at > datetime('now', '-1 day')
ORDER BY created_at DESC
LIMIT 20;
```

---

## Monitoring Queries

### Discovery Activity Dashboard

```sql
-- Recent discovery stats
.mode column
.headers on

SELECT 
    DATE(discovered_at) as date,
    COUNT(*) as urls_discovered,
    COUNT(DISTINCT source_host_id) as sources_active
FROM candidate_links
WHERE discovered_at >= DATE('now', '-7 days')
GROUP BY DATE(discovered_at)
ORDER BY date DESC;
```

### Source Health Check

```sql
-- Sources by last discovery date
SELECT 
    CASE 
        WHEN last_disc IS NULL THEN 'Never'
        WHEN DATE(last_disc) >= DATE('now', '-1 day') THEN 'Today'
        WHEN DATE(last_disc) >= DATE('now', '-7 days') THEN 'This Week'
        WHEN DATE(last_disc) >= DATE('now', '-30 days') THEN 'This Month'
        ELSE 'Over 30 Days'
    END as recency,
    COUNT(*) as source_count
FROM (
    SELECT 
        s.id,
        MAX(cl.discovered_at) as last_disc
    FROM sources s
    LEFT JOIN candidate_links cl ON s.id = cl.source_host_id
    GROUP BY s.id
)
GROUP BY recency
ORDER BY 
    CASE recency
        WHEN 'Today' THEN 1
        WHEN 'This Week' THEN 2
        WHEN 'This Month' THEN 3
        WHEN 'Over 30 Days' THEN 4
        ELSE 5
    END;
```

### Failure Analysis

```sql
-- Top failure types
SELECT 
    failure_type,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as percentage
FROM site_failures
WHERE created_at > datetime('now', '-1 day')
GROUP BY failure_type
ORDER BY count DESC
LIMIT 10;
```

---

## Best Practices

### 1. First-Time Setup

```bash
# 1. Validate setup
python scripts/validate_discovery_setup.py

# 2. Check status
python -m src.cli discovery-status

# 3. Run initial discovery (no scheduling)
python -m src.cli discover-urls --source-limit 5

# 4. Verify results
python -m src.cli discovery-status
```

### 2. Production Scheduled Runs

```bash
# Use --due-only for scheduled jobs
python -m src.cli discover-urls --due-only

# Or with dataset filtering
python -m src.cli discover-urls \
    --dataset Mizzou-Missouri-State \
    --due-only
```

### 3. Debugging Single Sources

```bash
# Debug specific source with verbose logging
python -m src.cli discover-urls \
    --source "Source Name" \
    --log-level DEBUG \
    --max-articles 10
```

### 4. Dataset-Specific Discovery

```bash
# Discover from specific dataset
python -m src.cli discover-urls \
    --dataset Mizzou-Missouri-State \
    --source-limit 50

# Check what would run with scheduling
python -m src.cli discovery-status \
    --dataset Mizzou-Missouri-State
```

---

## Logging and Telemetry

### Enable Debug Logging

```bash
# Full debug output
python -m src.cli discover-urls \
    --log-level DEBUG \
    --source-limit 5

# Save logs to file
python -m src.cli discover-urls \
    --log-level DEBUG 2>&1 | tee discovery.log
```

### Key Log Messages

**Success**:
```
✓ [1/10] Sikeston Standard Democrat: 15 new URLs
```

**Scheduling**:
```
⏭️ Skipping Source Name: not due (frequency=daily, last_discovery=2025-10-20T10:00:00)
```

**Dataset Validation**:
```
✓ Dataset 'Mizzou-Missouri-State' validated: 42 sources
```

**Errors**:
```
❌ Dataset 'InvalidName' not found in database
Available datasets: dataset1, dataset2
```

---

## Emergency Recovery

### Reset Discovery Schedule

If sources are stuck in "not due" state:

```python
# Reset last_discovery_at for all sources
from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager('sqlite:///data/mizzou.db')
with db.engine.begin() as conn:
    # Reset metadata for all sources
    conn.execute(text("""
        UPDATE sources 
        SET metadata = json_set(
            COALESCE(metadata, '{}'),
            '$.last_discovery_at',
            NULL
        )
    """))
print("Discovery schedule reset - all sources now eligible")
```

### Clear Failed RSS Markers

If sources are skipped due to `rss_missing` flags:

```python
from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager('sqlite:///data/mizzou.db')
with db.engine.begin() as conn:
    conn.execute(text("""
        UPDATE sources 
        SET metadata = json_remove(
            metadata,
            '$.rss_missing',
            '$.rss_consecutive_failures'
        )
        WHERE metadata IS NOT NULL
    """))
print("RSS failure markers cleared")
```

---

## Performance Tuning

### Optimize for Large Source Lists

```bash
# Process in batches
python -m src.cli discover-urls --source-limit 100 --due-only

# Filter by city/county for parallel processing
python -m src.cli discover-urls --city "Springfield" &
python -m src.cli discover-urls --city "Columbia" &
wait
```

### Proxy Configuration

```bash
# Use proxy pool for rate limiting
export PROXY_POOL="http://proxy1:8080,http://proxy2:8080"
python -m src.cli discover-urls

# Use origin proxy adapter
export USE_ORIGIN_PROXY=true
export ORIGIN_PROXY_URL="http://origin-proxy:3000"
python -m src.cli discover-urls
```

---

## Getting Help

### Diagnostic Report

Generate a diagnostic report for support:

```bash
#!/bin/bash
# Save as: generate_diagnostic_report.sh

echo "=== Discovery Diagnostic Report ===" > discovery_report.txt
echo "Generated: $(date)" >> discovery_report.txt
echo "" >> discovery_report.txt

echo "=== System Info ===" >> discovery_report.txt
python --version >> discovery_report.txt
echo "" >> discovery_report.txt

echo "=== Discovery Status ===" >> discovery_report.txt
python -m src.cli discovery-status >> discovery_report.txt 2>&1
echo "" >> discovery_report.txt

echo "=== Validation ===" >> discovery_report.txt
python scripts/validate_discovery_setup.py >> discovery_report.txt 2>&1
echo "" >> discovery_report.txt

echo "=== Recent Errors ===" >> discovery_report.txt
sqlite3 data/mizzou.db "
SELECT created_at, error_message 
FROM site_failures 
ORDER BY created_at DESC 
LIMIT 10;" >> discovery_report.txt

echo "Report saved to: discovery_report.txt"
```

### Common Support Resources

1. **Check Documentation**: `/docs/troubleshooting/DISCOVERY_PIPELINE.md` (this file)
2. **Review Logs**: Enable `--log-level DEBUG` for detailed output
3. **Run Validation**: `python scripts/validate_discovery_setup.py`
4. **Check Status**: `python -m src.cli discovery-status`
5. **Review Telemetry**: Query `discovery_method_effectiveness` table

---

## Changelog

### Version 2.0 (October 21, 2025)
- Added database compatibility layer (SQLite + PostgreSQL)
- Changed `--due-only` default to `False`
- Added dataset validation with clear error messages
- Added `discovery-status` CLI command
- Enhanced logging for filtered sources
- Created validation script

### Version 1.0 (Earlier)
- Initial discovery pipeline
- Basic scheduling support
- RSS and newspaper4k integration
