# Weekly Health Check Cloud Function - Deployment Summary

## ✅ Status: ACTIVE & OPERATIONAL

**Deployed**: 2026-01-31 16:17:06 UTC  
**Last Test**: SUCCESS (1,912 articles analyzed, 50 sources)  
**Next Scheduled Run**: 2026-02-02 06:00:00 UTC (Monday 6 AM)

---

## Function Details

### Deployment Info
- **Function Name**: `mizzou-weekly-health-check`
- **Project**: `mizzou-news-crawler`
- **Region**: `us-central1`
- **Runtime**: Python 3.11
- **Memory**: 512 MB
- **Timeout**: 600 seconds (10 minutes)
- **Revision**: `mizzou-weekly-health-check-00005-...`
- **State**: ACTIVE

### Entry Point
- **Function**: `send_weekly_health_check(request)`
- **Source**: `gcp/functions/weekly-health-check/main.py`

### HTTP Endpoint
```
https://mizzou-weekly-health-check-kgsyuk6v4q-uc.a.run.app/
```

---

## Configuration

### Environment Variables
```
BQ_PROJECT_ID = mizzou-news-crawler
GMAIL_DELEGATED_USER = chair@localnewsimpact.org
REPORT_TO_EMAIL = chair@localnewsimpact.org
```

### Secrets
- **GMAIL_CREDENTIALS_JSON** (Secret Manager)
  - Secret: `gmail-credentials`
  - Version: `latest`
  - Scope: Gmail API with domain-wide delegation

### Service Account
- Email: `145096615031-compute@developer.gserviceaccount.com`
- Permissions: BigQuery (`roles/bigquery.dataViewer`), Gmail API access

---

## Data Source

### BigQuery Query
The function queries `mizzou_analytics.articles` table for the past 7 days:

```sql
SELECT 
    REGEXP_EXTRACT(a.url, r'https?://([^/]+)') as hostname,
    COUNT(*) as article_count,
    MAX(CAST(a.extracted_at AS TIMESTAMP)) as last_extraction
FROM `mizzou-news-crawler.mizzou_analytics.articles` a
WHERE CAST(a.extracted_at AS TIMESTAMP) >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY hostname
ORDER BY article_count DESC
LIMIT 50
```

### Test Results
- **Execution Time**: ~2 seconds
- **Sources Analyzed**: 50 (top by volume)
- **Total Articles**: 1,912 (last 7 days)
- **Email Status**: ✅ Sent successfully

---

## Email Report

### Recipients
- `chair@localnewsimpact.org`

### Report Contents
- **Header**: "Weekly Source Activity Report"
- **Summary Section**:
  - Total active sources (7-day window)
  - Total articles extracted
  - Average articles per source
- **Table**:
  - Top 20 sources ranked by volume
  - Article count
  - Last extraction timestamp
- **Format**: HTML email with styled table

### Sample Output (Test Run)
```
Active Sources: 50
Total Articles: 1,912
Average per Source: 38
```

---

## Cloud Scheduler Integration

### Job Configuration
- **Job Name**: `health-check-weekly`
- **Location**: `us-central1`
- **Schedule**: `0 6 * * 1` (Monday 6:00 AM UTC)
- **State**: ENABLED
- **HTTP Method**: GET
- **Timeout**: 180 seconds
- **Retry Policy**: Max 5 doublings, 5-3600s backoff

### Trigger
- Invokes Cloud Function via OIDC token
- Automatic retry on failures
- Service account authentication

### Next Executions
- 2026-02-02 06:00:00 UTC (Monday)
- 2026-02-09 06:00:00 UTC (Monday)
- 2026-02-16 06:00:00 UTC (Monday)
- ... (weekly thereafter)

---

## Infrastructure Reuse

### Existing Components Leveraged
1. **Gmail Infrastructure**
   - Service account from `daily-report` function
   - Domain-wide delegation already configured
   - Secret Manager integration established

2. **BigQuery Connection**
   - Native GCP BigQuery client
   - Project credentials from function environment
   - Analytics dataset already populated

3. **Email Pattern**
   - Reused from `daily-report` function
   - Service account + delegated credentials approach
   - HTML + plain text multipart format

### Build & Dependencies
- Requirements: `google-cloud-bigquery`, `google-api-python-client`, `google-auth-oauthlib`
- Build time: ~3 minutes
- Container size: Minimal (no database drivers needed)

---

## Testing

### Manual Test (2026-01-31 16:17:17 UTC)
```bash
gcloud functions call mizzou-weekly-health-check --region=us-central1 --gen2
```

**Response** ✅
```json
{
  "status": "success",
  "message": "Weekly source activity report sent",
  "timestamp": "2026-01-31T16:17:17.390135",
  "sources_analyzed": 50,
  "total_articles": 1912,
  "recipients": ["chair@localnewsimpact.org"],
  "message_id": "19c14d82b35773d2"
}
```

---

## Logs & Monitoring

### View Recent Logs
```bash
gcloud functions logs read mizzou-weekly-health-check --region=us-central1 --gen2 --limit=50
```

### Key Log Entries
- ✅ Decoding Gmail credentials
- ✅ Querying BigQuery for source activity
- ✅ Generating HTML report
- ✅ Creating Gmail credentials
- ✅ Sending email

### Common Debug Commands
```bash
# Describe function
gcloud functions describe mizzou-weekly-health-check --gen2 --region=us-central1

# Check scheduler job
gcloud scheduler jobs describe health-check-weekly --location=us-central1

# Get function details
gcloud functions logs read mizzou-weekly-health-check --region=us-central1 --gen2 --limit=20
```

---

## Maintenance & Troubleshooting

### If Email Doesn't Arrive
1. Check function logs: `gcloud functions logs read ...`
2. Verify Gmail credentials: Check Secret Manager `gmail-credentials`
3. Verify recipient email in environment variables
4. Verify domain-wide delegation is configured in Google Workspace

### If BigQuery Query Fails
1. Check data availability: Query `mizzou_analytics.articles` directly
2. Verify TIMESTAMP casting (extracted_at column)
3. Check BigQuery dataset permissions for service account
4. Review column names if schema changed

### If Scheduler Doesn't Trigger
1. Verify job is ENABLED: `gcloud scheduler jobs describe health-check-weekly ...`
2. Check job status in Cloud Console
3. Manually trigger: `gcloud scheduler jobs run health-check-weekly --location=us-central1`
4. Review Cloud Scheduler logs

---

## Next Steps

### Monitoring
- [ ] Monitor first scheduled execution (Feb 2, 2026 6 AM UTC)
- [ ] Verify email arrives at `chair@localnewsimpact.org`
- [ ] Check report accuracy against expected data

### Enhancement Ideas
1. Add source-level filtering (only problem sources)
2. Include wire service detection status
3. Add alerts for sources with no recent activity
4. Implement HTML-to-PDF for archived reports
5. Add CSV attachment to email

### Documentation
- [Daily Report Function](../daily-report/README.md)
- [BigQuery Schema](../../../bigquery/schema.sql)
- [Cloud Scheduler Setup Guide](../../../docs/cloud-scheduler-setup.md)

---

## Contacts & Support

- **Report Recipient**: `chair@localnewsimpact.org`
- **Service Account**: `145096615031-compute@developer.gserviceaccount.com`
- **Project**: `mizzou-news-crawler`
- **Region**: `us-central1`

---

**Last Updated**: 2026-01-31 16:17:06 UTC  
**Status**: ✅ Production Ready
