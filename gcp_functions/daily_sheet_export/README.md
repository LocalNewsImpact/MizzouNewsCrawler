# Daily Google Sheets Export Function

Cloud Function that exports BigQuery analytics data to Google Sheets on a daily schedule.

## Overview

This function queries the `mizzou_analytics.articles` table in BigQuery and appends results to a Google Sheet. It filters out wire service content, obituaries, and opinion pieces, and exports all eligible articles per day (no limit).

**Target Sheet**: [Active Month Tab](https://docs.google.com/spreadsheets/d/1_0T4QeDUCBOSU7qXOkszhYVf2_6XATub8DsXBaORgwI)

## Files

- **`main.py`** - Cloud Function entry point (`export_daily_analytics`)
- **`requirements.txt`** - Python dependencies

## Deployment

**CRITICAL**: Always deploy from the workspace root directory, not from within the function directory.

```bash
# From workspace root (/Users/kiesowd/VSCode/NewsCrawler/MizzouNewsCrawler)
gcloud functions deploy export-daily-analytics \
  --gen2 \
  --runtime python311 \
  --region us-central1 \
  --source gcp_functions/daily_sheet_export \
  --entry-point export_daily_analytics \
  --trigger-http \
  --memory 512MB \
  --timeout 540s \
  --no-allow-unauthenticated \
  --service-account mizzou-k8s-sa@mizzou-news-crawler.iam.gserviceaccount.com
```

### Deployment Checklist

1. **Verify working directory**: Must be workspace root
   ```bash
   pwd  # Should show: /Users/kiesowd/VSCode/NewsCrawler/MizzouNewsCrawler
   ```

2. **Service account**: `mizzou-k8s-sa@mizzou-news-crawler.iam.gserviceaccount.com`
   - This service account has permissions for BigQuery and Sheets API
   - Other service accounts will fail with organization policy errors

3. **Authentication**: Use `--no-allow-unauthenticated` (NOT `--allow-unauthenticated`)
   - Organization policy prevents unauthenticated access
   - Function is triggered by Cloud Scheduler with proper auth

4. **Source path**: `gcp_functions/daily_sheet_export` (relative to workspace root)

## Configuration

### Environment Variables

All configuration is hardcoded in `main.py`:
- `PROJECT_ID`: `mizzou-news-crawler`
- `SHEET_ID`: `1_0T4QeDUCBOSU7qXOkszhYVf2_6XATub8DsXBaORgwI`
- `SHEET_RANGE`: `'Active Month'!A1`

### Required IAM Permissions

The service account needs:
- **BigQuery**: `roles/bigquery.dataViewer` or `roles/bigquery.jobUser`
- **Google Sheets API**: Enabled with appropriate OAuth scopes
- **Cloud Functions**: `roles/cloudfunctions.developer`

## Usage

### Query Parameters

- `date`: Single day to export (YYYY-MM-DD)
- `start_date` + `end_date`: Date range (inclusive)
- `limit`: Max rows per day (default: 750, max: 750)
- `dry_run`: Set to `true` to test without writing to Sheets

### Examples

```bash
# Export yesterday (default behavior)
curl -X POST https://us-central1-mizzou-news-crawler.cloudfunctions.net/export-daily-analytics \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"

# Export specific date
curl -X POST https://us-central1-mizzou-news-crawler.cloudfunctions.net/export-daily-analytics?date=2026-02-14 \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"

# Export date range
curl -X POST "https://us-central1-mizzou-news-crawler.cloudfunctions.net/export-daily-analytics?start_date=2026-02-01&end_date=2026-02-05" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"

# Dry run (test without writing)
curl -X POST "https://us-central1-mizzou-news-crawler.cloudfunctions.net/export-daily-analytics?dry_run=true" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"
```

### Local Testing

```bash
# From workspace root
python gcp_functions/daily_sheet_export/main.py --date 2026-02-14
python gcp_functions/daily_sheet_export/main.py --start_date 2026-02-01 --end_date 2026-02-05 --limit 200
python gcp_functions/daily_sheet_export/main.py --dry_run true
```

## Data Schema

### BigQuery Query

```sql
SELECT 
    IFNULL(title, '') as title,
    IFNULL(url, '') as url,
    IFNULL(author, '') as author,
    IFNULL(SUBSTR(text, 0, 50000), '') as text,
    FORMAT_DATE("%Y-%m-%d", DATE(publish_date)) as publish_date,
    FORMAT_DATE("%Y-%m-%d", DATE(extracted_at)) as extracted_at,
    IFNULL(status, '') as status,
    IFNULL(primary_label, '') as primary_label,
    IFNULL(alternate_label, '') as alternate_label
FROM `mizzou-news-crawler.mizzou_analytics.articles`
WHERE DATE(TIMESTAMP(extracted_at, "America/Chicago")) = DATE('{target_day}')
  AND status NOT IN ('wire', 'obituary', 'opinion')
ORDER BY extracted_at DESC
LIMIT 750
```

### Google Sheet Columns

1. **ID** - Serial number (auto-incremented)
2. **Host Name** - Domain extracted from URL
3. **Title** - Article headline
4. **URL** - Full article URL
5. **Author** - Byline
6. **Text** - Article content (truncated to 50k chars)
7. **Publish Date** - YYYY-MM-DD format
8. **Extracted At** - YYYY-MM-DD format
9. **Status** - Processing status
10. **Primary Label** - CIN classification
11. **Alternate Label** - Secondary classification

## Monitoring

### Cloud Function Logs

```bash
gcloud functions logs read export-daily-analytics \
  --region us-central1 \
  --limit 50
```

### Verify Deployment

```bash
gcloud functions describe export-daily-analytics \
  --gen2 \
  --region us-central1 \
  --format="table(name,state,updateTime,serviceConfig.serviceAccountEmail)"
```

## Troubleshooting

### Error: "does not belong to a permitted customer"

**Cause**: Using `--allow-unauthenticated` violates organization policy.

**Fix**: Use `--no-allow-unauthenticated` instead.

### Error: "Service account was not found"

**Cause**: Wrong service account name.

**Fix**: Use exact name: `mizzou-k8s-sa@mizzou-news-crawler.iam.gserviceaccount.com`

### Error: "Provided directory does not exist"

**Cause**: Wrong working directory or incorrect source path.

**Fix**: 
1. Change to workspace root: `cd /Users/kiesowd/VSCode/NewsCrawler/MizzouNewsCrawler`
2. Use relative source path: `--source gcp_functions/daily_sheet_export`

### No data exported

**Check**:
1. BigQuery has data for the target date
2. Date range uses Central Time (America/Chicago)
3. Status filter excludes wire/obituary/opinion articles
4. Google Sheet permissions allow the service account to write

### ⚠️ CRITICAL: Filtered/Sorted Sheets (FIXED as of 2026-02-27)

**Previous Issue**: If the sheet was filtered or sorted when the export ran, the ID counter would only count visible rows, causing duplicate IDs and data loss.

**Fix Applied**: Now uses sheet metadata (`gridProperties.rowCount`) instead of counting visible values, which correctly handles filtered/sorted sheets.

**Recovery**: If you lost 2-3 days of exports:
1. Check Cloud Functions logs for the affected date range
2. Re-run the export with date parameters:
   ```bash
   curl -X POST "https://us-central1-mizzou-news-crawler.cloudfunctions.net/export-daily-analytics?start_date=2026-02-24&end_date=2026-02-26" \
     -H "Authorization: Bearer $(gcloud auth print-identity-token)"
   ```

**Best Practice**: Clear all filters before running manual exports (automated runs are now safe).

