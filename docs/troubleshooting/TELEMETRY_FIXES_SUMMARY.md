# Telemetry Fixes Summary

**Date**: October 20, 2025  
**Branch**: feature/gcp-kubernetes-deployment

## Issues Fixed

### 1. ✅ Byline Cleaning Telemetry - Missing `created_at` (Commit: fe9659f)

**Error:**
```
null value in column "created_at" of relation "byline_cleaning_telemetry" violates not-null constraint
```

**Root Cause:**
- Database table has `created_at` column with NOT NULL constraint
- INSERT statement was missing the `created_at` column
- Only 27 parameters provided, but 28 needed

**Fix:**
- Added `created_at` column to INSERT statement in `src/utils/byline_telemetry.py`
- Set value to `datetime.utcnow()` as 28th parameter
- Updated VALUES clause from 27 to 28 placeholders

**Files Changed:**
- `src/utils/byline_telemetry.py` (line 337-384)

### 2. ✅ 403 Bot Protection Backoff (Commit: e2e7d38)

**Issue:**
- Extraction was attempting URLs from domains that returned 403 (bot protection)
- Only 429 rate limits triggered immediate domain skip
- 403 responses should also skip remaining URLs from that domain in batch

**Fix:**
- Added 403 HTTP status to rate limit detection in extraction loop
- Check both error path and exception path
- Immediately add domain to `skipped_domains` on 403

**Files Changed:**
- `src/cli/commands/extraction.py` (lines ~915-930, 950-980)

### 3. ✅ Discovery Source Limit (Commit: 316e676)

**Issue:**
- Mizzou dataset has **157 sources**
- Discovery was only processing **50 sources** per run (--source-limit 50)
- Missing **107 sources** every 6 hours

**Fix:**
- Removed `--source-limit` parameter from CronWorkflow
- Set high default (10000) in WorkflowTemplate for backward compatibility
- Discovery now processes ALL sources in dataset each run

**Files Changed:**
- `k8s/argo/mizzou-pipeline-cronworkflow.yaml`
- `k8s/argo/base-pipeline-workflow.yaml`

### 4. ✅ Legacy Non-Article URLs (Commit: 38546cd)

**Issue:**
- 8 gallery/video URLs from before URL classifier (Oct 10) were in database
- Example: `https://www.kfvs12.com/video-gallery/news/`

**Fix:**
- Marked all 8 legacy gallery URLs as `status='filtered'`
- Added error message: "Non-article URL pattern (gallery/video page)"
- URL classifier now prevents new non-article URLs

**Documentation:**
- `LEGACY_NON_ARTICLE_CLEANUP.md`

## Previous Fixes (Referenced)

### ✅ Extraction Telemetry SQL Errors (Commits: ddb6667, 5c23c5c, f4f1cd7, bc638eb)
- Fixed placeholder count (31→30)
- Boolean→integer conversions for proxy fields
- Proxy status string→integer with status codes
- TelemetryStore integration with DatabaseManager

### ✅ Gazetteer Performance (Commit: 075b5e3)
- Fixed OR→AND bug (60-120x faster: 10-30 min → 30 sec per article)

### ✅ Foreign Key Constraint (Manual SQL)
- Dropped `fk_extraction_telemetry_article` constraint
- Allows telemetry recording for failed extractions

## Deployment Status

**Builds Queued:**
- Crawler: `e8f33811-654f-497b-b608-fcefe26df554` (fe9659f)
- Processor: `dc622655-45f8-4de5-afcd-a088a86912b5` (fe9659f)

**Images:**
- `crawler:fe9659f` (with 403 backoff + telemetry fix)
- `processor:fe9659f` (with telemetry fix)
- Both tagged as `:latest` and `:v1.3.1`

## Verification

After deployment completes, verify:

1. **Byline telemetry works:**
   ```bash
   kubectl logs -n production -l app=mizzou-crawler | grep "byline_cleaning_telemetry"
   ```
   Should see successful inserts, no constraint violations

2. **403 domains are skipped:**
   ```bash
   kubectl logs -n production -l app=mizzou-crawler | grep "403\|bot protection"
   ```
   Should see "skipping remaining URLs in batch" after 403

3. **All sources processed:**
   ```sql
   SELECT COUNT(*) FROM sources 
   WHERE id IN (SELECT DISTINCT source_host_id FROM candidate_links)
   ```
   Should approach 157 sources over time

## Remaining Work

- Monitor telemetry for other potential missing columns
- Check if other telemetry tables have similar issues
- Consider adding integration tests for telemetry SQL statements
