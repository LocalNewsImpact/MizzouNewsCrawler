# Articles URL Deduplication Migration Runbook

## Overview

This runbook documents the procedure to add a unique constraint on `articles.url` to prevent duplicate article insertion at the database level. This addresses GitHub Issue #105.

**Migration ID:** `20251025_add_uq_articles_url`  
**Status:** Ready for deployment  
**Risk Level:** Medium (requires deduplication before applying)  

## Background

### Problem
The extraction process currently uses `ON CONFLICT DO NOTHING` to handle duplicate article URLs, but the database lacks the required unique constraint. This can lead to:
- Runtime errors if the constraint is referenced without existing
- Potential duplicate articles if the conflict handling is bypassed
- Unclear database schema expectations

### Solution
Add a `UNIQUE INDEX` on `articles.url` column to:
1. Enforce URL uniqueness at the database level
2. Enable safe use of `ON CONFLICT` clauses
3. Prevent duplicate article insertions
4. Improve data integrity

## Pre-Migration Requirements

### 1. Stop Extraction Jobs
**Critical:** Stop all extraction jobs before beginning deduplication to prevent new duplicates from being created during the process.

```bash
# Pause all extraction cron jobs
kubectl scale deployment extraction --replicas=0 -n production

# Verify no extraction jobs are running
kubectl get pods -n production | grep extraction
```

### 2. Backup Database
Create a backup before making any changes:

```bash
# PostgreSQL backup (Cloud SQL)
gcloud sql backups create \
  --instance=INSTANCE_NAME \
  --description="Pre-deduplication backup $(date +%Y%m%d)"

# Or use pg_dump for a logical backup
pg_dump -Fc -f backup_pre_dedupe_$(date +%Y%m%d).dump "$DATABASE_URL"
```

### 3. Verify Backup
Confirm the backup completed successfully:

```bash
# List recent backups
gcloud sql backups list --instance=INSTANCE_NAME --limit=5

# Verify backup size is reasonable
ls -lh backup_pre_dedupe_*.dump
```

## Migration Steps

### Step 1: Analyze Duplicates

Run the deduplication script in dry-run mode to analyze the scope:

```bash
# From repository root
python scripts/fix_article_duplicates.py --dry-run
```

**Expected output:**
```
2025-10-25 12:52:00 - INFO - Analyzing duplicate articles...
2025-10-25 12:52:01 - INFO - Found 15 URLs with duplicates
2025-10-25 12:52:01 - INFO - Total duplicate article records to remove: 23
2025-10-25 12:52:01 - INFO - Top duplicate URLs:
  - https://example.com/article1: 3 copies
  - https://example.com/article2: 2 copies
  ...
```

**Action:** Review the output and estimate impact. If duplicates are excessive, investigate root cause before proceeding.

### Step 2: Run Deduplication

Execute the deduplication script to remove duplicates:

```bash
# Interactive mode (with confirmation prompt)
python scripts/fix_article_duplicates.py

# Non-interactive mode (use with caution)
python scripts/fix_article_duplicates.py --yes
```

**What it does:**
1. Deletes child records (`article_labels`, `article_entities`, `ml_results`) for duplicate articles
2. Deletes duplicate articles, keeping the most recent by `extracted_at` timestamp
3. Verifies cleanup was successful

**Deduplication policy:**
- Keeps: Most recent article (highest `extracted_at`)
- Deletes: Older duplicates and their child records

**Important:** The script will prompt for confirmation before making changes. Review carefully.

### Step 3: Verify Deduplication

Confirm no duplicates remain:

```bash
# Re-run analysis
python scripts/fix_article_duplicates.py --dry-run
```

**Expected output:**
```
2025-10-25 12:55:00 - INFO - ✓ No duplicate URLs found
```

### Step 4: Run Alembic Migration

Apply the database migration to add the unique constraint:

```bash
# Check current revision
alembic current

# Run migration
alembic upgrade 20251025_add_uq_articles_url

# Verify migration succeeded
alembic current
```

**Expected output:**
```
INFO  [alembic.runtime.migration] Running upgrade 805164cd4665 -> 20251025_add_uq_articles_url
```

**For PostgreSQL production:**
- Migration uses `CREATE UNIQUE INDEX CONCURRENTLY`
- Minimal locking - safe to run on live database
- May take several minutes on large tables

**For SQLite development:**
- Standard index creation (no CONCURRENTLY support)
- Fast on small databases

### Step 5: Verify Constraint

Confirm the unique constraint exists:

```bash
# PostgreSQL
psql "$DATABASE_URL" -c "\\d articles"
# Look for: "uq_articles_url" UNIQUE, btree (url)

# Or query pg_indexes
psql "$DATABASE_URL" -c \
  "SELECT indexname, indexdef FROM pg_indexes 
   WHERE tablename='articles' AND indexname='uq_articles_url';"
```

**Expected output:**
```
     indexname      |                        indexdef                        
--------------------+--------------------------------------------------------
 uq_articles_url    | CREATE UNIQUE INDEX uq_articles_url ON public.articles USING btree (url)
```

### Step 6: Test Duplicate Prevention

Verify the constraint prevents duplicates:

```bash
# Try inserting a duplicate (should be silently ignored)
psql "$DATABASE_URL" << 'EOF'
-- Insert test article
INSERT INTO articles (id, candidate_link_id, url, title, status, extracted_at, created_at, text_hash)
SELECT 
  gen_random_uuid()::text,
  cl.id,
  'https://test-duplicate-prevention.example',
  'Test Article',
  'extracted',
  NOW(),
  NOW(),
  'test-hash'
FROM candidate_links cl
LIMIT 1
ON CONFLICT DO NOTHING;

-- Try inserting duplicate (should do nothing)
INSERT INTO articles (id, candidate_link_id, url, title, status, extracted_at, created_at, text_hash)
SELECT 
  gen_random_uuid()::text,
  cl.id,
  'https://test-duplicate-prevention.example',
  'Duplicate Test',
  'extracted',
  NOW(),
  NOW(),
  'test-hash-2'
FROM candidate_links cl
LIMIT 1
ON CONFLICT DO NOTHING;

-- Verify only one article exists
SELECT COUNT(*) FROM articles WHERE url = 'https://test-duplicate-prevention.example';

-- Cleanup
DELETE FROM articles WHERE url = 'https://test-duplicate-prevention.example';
EOF
```

**Expected output:**
```
INSERT 0 1
INSERT 0 0
 count 
-------
     1
DELETE 1
```

### Step 7: Resume Extraction

Restart extraction jobs:

```bash
# Scale up extraction deployment
kubectl scale deployment extraction --replicas=1 -n production

# Monitor for errors
kubectl logs -f deployment/extraction -n production
```

## Monitoring

### Post-Migration Checks

Monitor extraction jobs for the first hour after resuming:

```bash
# Watch extraction job logs
kubectl logs -f -l app=extraction -n production --tail=100

# Check for constraint violations (should be none)
psql "$DATABASE_URL" -c \
  "SELECT * FROM pg_stat_user_tables WHERE relname='articles';"
```

### Metrics to Monitor

1. **Extraction success rate:** Should remain stable
2. **Article insertion rate:** Should be unchanged
3. **Database errors:** Should be zero
4. **Disk usage:** May decrease slightly after deduplication

### Expected Behavior

After migration:
- `ON CONFLICT DO NOTHING` will silently skip duplicate URLs
- No errors when attempting to insert duplicates
- Extraction logs may show fewer "article created" messages (duplicates skipped)

## Rollback Procedure

If issues arise, rollback the migration:

### Option 1: Downgrade Migration (Preferred)

```bash
# Rollback to previous revision
alembic downgrade 805164cd4665

# Verify rollback
alembic current
```

This removes the unique index but keeps data intact.

### Option 2: Restore from Backup (Last Resort)

If data corruption occurred:

```bash
# Stop all writes to database
kubectl scale deployment extraction --replicas=0 -n production
kubectl scale deployment processor --replicas=0 -n production

# Restore from backup
# For Cloud SQL:
gcloud sql backups restore BACKUP_ID \
  --backup-instance=INSTANCE_NAME \
  --backup-instance=INSTANCE_NAME

# For pg_dump backup:
pg_restore -d "$DATABASE_URL" -c backup_pre_dedupe_YYYYMMDD.dump
```

## Troubleshooting

### Migration Fails with "Duplicates Found"

**Error:**
```
RuntimeError: Cannot add unique constraint: Found 3 articles with URL 'https://example.com/article'.
Run scripts/fix_article_duplicates.py to remove duplicates before applying this migration.
```

**Solution:**
1. Run deduplication script: `python scripts/fix_article_duplicates.py`
2. Retry migration: `alembic upgrade head`

### Constraint Creation Hangs (PostgreSQL)

**Symptoms:**
- `CREATE INDEX CONCURRENTLY` takes longer than expected
- Database seems unresponsive

**Diagnosis:**
```sql
-- Check for locks
SELECT * FROM pg_locks WHERE relation::regclass::text = 'articles';

-- Check active queries
SELECT * FROM pg_stat_activity WHERE state = 'active';
```

**Solution:**
- Wait for completion (index creation on large tables can take time)
- Monitor progress via `pg_stat_progress_create_index`
- If truly hung (>30 minutes), may need to cancel and retry

### Extraction Jobs Fail After Migration

**Symptoms:**
- Extraction jobs log errors
- Articles not being inserted

**Diagnosis:**
```bash
# Check extraction logs
kubectl logs -l app=extraction -n production --tail=100

# Look for SQL errors
kubectl logs -l app=extraction -n production | grep -i "error\|exception"
```

**Common causes:**
1. Application code not using `ON CONFLICT DO NOTHING` (should already be in place)
2. Database connectivity issues
3. Unrelated extraction errors

**Solution:**
1. Verify extraction code uses `ON CONFLICT DO NOTHING` (line 104 in `src/cli/commands/extraction.py`)
2. Check database connectivity
3. Review extraction logs for specific errors

## Testing Checklist

Before declaring migration complete:

- [ ] Backup verified and accessible
- [ ] Deduplication completed successfully
- [ ] Migration applied without errors
- [ ] Unique index exists on `articles.url`
- [ ] Test insertion of duplicate URL succeeds with `ON CONFLICT DO NOTHING`
- [ ] Extraction jobs restarted successfully
- [ ] No errors in extraction logs for 1 hour
- [ ] Article insertion rate is normal
- [ ] Database monitoring shows no issues

## Reference

- **GitHub Issue:** #105
- **Migration file:** `alembic/versions/20251025_add_unique_articles_url.py`
- **Deduplication script:** `scripts/fix_article_duplicates.py`
- **Tests:** `tests/alembic/test_articles_url_constraint.py`
- **Extraction code:** `src/cli/commands/extraction.py` (line 92-105)

## Related Documentation

- [Alembic Migration Guide](ALEMBIC_TESTING.md)
- [Database Backup Procedures](ROLLBACK_PROCEDURE.md)
- [Extraction Pipeline Documentation](../features/EXTRACTION.md)
