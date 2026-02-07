# Weekly Health Check Cloud Function

Automated weekly source health diagnostics report sent via email every Monday 6 AM UTC.

## What It Does

Identifies **problematic sources** based on:
- **Extraction Rate**: % of discovered URLs verified as articles
- **Filter Rate**: % of discovered URLs filtered out (not articles)  
- **Recent Discoveries**: URLs found in last 7 days
- **Health Status**: Critical (0 extractions, <10% rate, >90% filter) or Warning (no recent activity, 10-30% rate, 70-90% filter)

## Report Contents

### 1. HTML Email
- **Summary section**: Count of critical and warning sources
- **Top 20 Problematic Sources table** with:
  - Source hostname
  - Health status (🔴 Critical or 🟠 Warning)
  - Recent discoveries (7-day count)
  - Extraction rate (%)
  - Filter rate (%)
  - Last discovery timestamp
- **Diagnostic explanations** of each metric
- Color-coded rows (red for critical, orange for warning)

### 2. CSV Attachment
For spreadsheet analysis with columns:
- rank, hostname, health_status
- recent_discoveries_7d, extraction_rate, filter_rate
- last_discovery, total_discovered_14d, verified_count, filtered_count

## Quick Start

### Manual Test
```bash
gcloud functions call mizzou-weekly-health-check --region=us-central1 --gen2
```

### Deploy
```bash
gcloud functions deploy mizzou-weekly-health-check \
  --gen2 \
  --region=us-central1 \
  --source=. \
  --entry-point=send_weekly_health_check \
  --runtime=python311 \
  --memory=512MB \
  --timeout=600s
```

### View Logs
```bash
gcloud functions logs read mizzou-weekly-health-check --region=us-central1 --gen2 --limit=50
```

## Configuration

Required environment variables (automatically set):
- `BQ_PROJECT_ID`: GCP project ID
- `GMAIL_DELEGATED_USER`: Sender email address
- `REPORT_TO_EMAIL`: Recipient email address

Required secret (from Secret Manager):
- `GMAIL_CREDENTIALS_JSON`: Base64-encoded service account JSON

## How It Works

1. **Query BigQuery**: 
   - `candidate_links` table for discovery/verification metrics (14-day window)
   - `articles` table for extraction metrics (14-day window)
   - Calculate extraction and filter rates per source
   
2. **Classify Sources**:
   - **Critical**: 0 extractions, <10% extraction rate, or >90% filter rate
   - **Warning**: No recent discoveries, 10-30% extraction rate, or 70-90% filter rate
   - **Healthy**: All others

3. **Generate Report**:
   - Rank problematic sources by severity then metrics
   - Create HTML email with styled table
   - Attach CSV with full dataset

4. **Send Email**:
   - Gmail API with domain-wide delegation
   - To: `chair@localnewsimpact.org`
   - Automated via Cloud Scheduler (Mondays 6 AM UTC)

## Data Metrics

### Per-Source Calculations
```
Extraction Rate (%) = (Verified Articles / Total Discovered) × 100
Filter Rate (%) = (Filtered URLs / Total Discovered) × 100
Recent Discoveries = URLs discovered in last 7 days
```

### Time Windows
- **14-day window**: All discovery and extraction metrics
- **7-day window**: Recent discovery count for warning detection
- **Reports**: Last 100 problematic sources, top 20 shown

## Example Test Output

```json
{
  "status": "success",
  "message": "Weekly source health report sent",
  "timestamp": "2026-01-31T16:24:59.187452",
  "total_sources": 100,
  "critical_sources": 100,
  "warning_sources": 0,
  "problematic_sources": 100,
  "recipients": ["chair@localnewsimpact.org"],
  "message_id": "19c14df360bde725"
}
```

## Troubleshooting

### Function fails with schema error
Check BigQuery tables exist:
```bash
bq ls --dataset_id mizzou-news-crawler:mizzou_analytics
bq show mizzou-news-crawler:mizzou_analytics.candidate_links
bq show mizzou-news-crawler:mizzou_analytics.articles
```

### Email not delivered
1. Verify recipient in `REPORT_TO_EMAIL` env var
2. Check Gmail credentials secret exists and is valid
3. Verify domain-wide delegation is configured in Google Workspace
4. Check function logs for errors: `gcloud functions logs read ...`

### Scheduler not triggering
```bash
# Check job status
gcloud scheduler jobs describe health-check-weekly --location=us-central1

# Manually trigger
gcloud scheduler jobs run health-check-weekly --location=us-central1

# View scheduler logs
gcloud functions logs read mizzou-weekly-health-check --region=us-central1 --gen2 --limit=50
```

## Files

- `main.py` - Cloud Function implementation
- `requirements.txt` - Python dependencies
- `DEPLOYMENT_SUMMARY.md` - Detailed configuration reference

## Infrastructure Reuse

- Gmail service account from `daily-report` function
- BigQuery analytics dataset and tables
- Cloud Scheduler infrastructure
- Service account permissions

## Related

- [Daily Report Function](../daily-report/) - Similar pattern, daily execution
- [Source Health Check Script](../../scripts/source_health_check.py) - Original diagnostic logic

