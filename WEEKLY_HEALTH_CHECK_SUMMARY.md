# Weekly Source Health Check System - Implementation Summary

**Status**: ✓ Complete and Ready for Deployment

---

## What Was Built

A fully automated weekly health check system that:

1. **Diagnoses all 193+ news sources** for collection pipeline health
2. **Generates comprehensive metrics** on discovery, extraction, filtering
3. **Identifies issues automatically**: paused sources, discovery failures, extraction problems, high filter rates
4. **Sends formatted HTML email reports** to specified recipient with:
   - Summary metrics (healthy/warning/critical counts)
   - Table of problematic sources (top 20)
   - CSV attachment with full source-by-source data
   - JSON attachment with raw metrics for archival
5. **Uploads backups to GCS** for long-term storage
6. **Runs on a schedule** (weekly by default, configurable)

---

## Files Created/Modified

### Core Infrastructure

| File | Purpose | Status |
|------|---------|--------|
| `scripts/source_health_check.py` | Health diagnostic engine | ✓ Existing (verified working) |
| `gcp_functions/weekly_source_health_check/main.py` | Cloud Function wrapper + email delivery | ✓ Created |
| `gcp_functions/weekly_source_health_check/requirements.txt` | Python dependencies | ✓ Updated |

### Documentation

| File | Purpose |
|------|---------|
| `WEEKLY_HEALTH_CHECK_DEPLOYMENT.md` | 200+ line deployment guide with full step-by-step instructions |
| `WEEKLY_HEALTH_CHECK_QUICKSTART.md` | Quick reference card for one-command setup |
| `scripts/test_health_check.py` | Comprehensive test suite to verify configuration |

---

## Health Check Dimensions

The system monitors 4 key health dimensions per source:

### 1. Database Status
- Is the source paused?
- RSS consecutive failures
- When was it last paused?

### 2. Discovery Activity
- Total articles discovered (all time)
- Articles discovered in past 30 days
- Discovery rate trend

### 3. Extraction Success
- Total articles extracted
- Recent extractions (past 30 days)
- Extraction rate (% of discovered articles that get extracted)

### 4. Filtering & Classification
- Total filtered as non-news (obituary/opinion/not_article)
- Recent filtered
- Filter rate

## Status Classification

Sources are classified as:

- **HEALTHY**: All metrics normal, active collection, good extraction/filter rates
- **WARNING**: Some metrics degraded (e.g., discovery slowdown but extraction still working)
- **CRITICAL**: Severe issues (paused, no discovery, extraction failing, high filter rate)
- **ERROR**: System couldn't diagnose (data collection error)

---

## Email Report Structure

**Subject**: `Weekly Source Health Report - YYYY-MM-DD`

**Body**:
```
Weekly Source Health Report
Generated: 2025-02-10 06:00:00 UTC

Summary
✓ Healthy: 175
⚠ Warnings: 12  
✗ Critical: 6

Critical Issues (6 sources)
• Buffalo Reflex: NO_DISCOVERY, EXTRACTION_RATE_LOW
• Source B: PAUSED_TECHNICAL
...

Warnings (12 sources)
• Source X: DISCOVERY_RATE_DECLINING
...

Top Issues Detail
[Table showing status, recent discoveries, extraction/filter rates]

Full detailed report attached as CSV and JSON files.
```

**Attachments**:
- `source_health_20250210_060000.csv` - Full diagnostics in spreadsheet format
- `source_health_20250210_060000.json` - Raw metrics for archival

---

## Deployment Path

### Before You Start
1. ✓ Google Cloud project with appropriate APIs enabled
2. ✓ Gmail account with app-specific password generated
3. ✓ GCS bucket (optional, for backups)

### Deployment Steps (see DEPLOYMENT.md for details)

1. **Create Secrets** (5 min)
   ```bash
   gcloud secrets create news-crawler-email --data-file=-
   gcloud secrets create news-crawler-email-password --data-file=-
   gcloud secrets create health-check-recipient-email --data-file=-
   ```

2. **Deploy Cloud Function** (2 min)
   ```bash
   gcloud functions deploy weekly-source-health-check --gen2 ...
   ```

3. **Grant IAM Permissions** (2 min)
   - Secret Manager access for service account
   - Cloud SQL access for service account
   - Storage permissions for GCS uploads

4. **Create Scheduler** (1 min)
   ```bash
   gcloud scheduler jobs create http health-check-weekly \
     --schedule "0 6 * * 1"  # Monday 6 AM UTC
   ```

5. **Test** (5 min)
   ```bash
   gcloud functions call weekly-source-health-check --gen2
   ```

**Total setup time**: ~15 minutes

---

## Key Configuration Details

### Environment Variables
- `HEALTH_CHECK_EMAIL`: Email recipient (can override via Secret Manager)
- `DATABASE_URL`: PostgreSQL connection (for local testing)

### Secrets (Google Secret Manager)
- `news-crawler-email`: Sender Gmail address
- `news-crawler-email-password`: Gmail app-specific password
- `health-check-recipient-email`: Report recipient

### Schedule Formats (cron)
- `0 6 * * 1` = Weekly Monday 6 AM UTC
- `0 6 * * *` = Daily 6 AM UTC  
- `0 */6 * * *` = Every 6 hours
- `0 3 * * 0` = Weekly Sunday 3 AM UTC

### Resource Requirements
- Memory: 512 MB
- Timeout: 540 seconds (9 min)
- Runtime: ~3-5 minutes for 193 sources

---

## Testing

### Local Testing
```bash
# Run test suite to verify all components
python scripts/test_health_check.py

# Tests:
# ✓ Imports (source_health_check, DatabaseManager)
# ✓ Database connectivity
# ✓ Health check logic on sample sources
# ✓ Report export (CSV/JSON)
# ✓ Email configuration (in GCP)
```

### Manual Cloud Function Test
```bash
gcloud functions call weekly-source-health-check --gen2 --region us-central1
```

### Scheduled Trigger Test
```bash
# Manually trigger scheduler job
gcloud scheduler jobs run health-check-weekly --location us-central1

# Monitor logs
gcloud functions logs read weekly-source-health-check --gen2 --limit 50
```

---

## Troubleshooting

| Issue | Diagnosis | Fix |
|-------|-----------|-----|
| Email not received | Check `gcloud functions logs` for SMTP errors | Verify Gmail credentials, 2FA enabled, app password correct |
| Function times out | Check log for which source hangs | Increase timeout to 900s or exclude problematic source |
| Database connection fails | Connection error in logs | Verify service account has `cloudsql.client` role |
| Scheduler doesn't trigger | Check scheduler status | Verify service account has `run.invoker` permission |
| GCS upload fails | Non-fatal, report still emailed | Verify bucket exists and service account has `storage.objectCreator` role |

---

## Customization Examples

### Change Report Frequency
```bash
# From weekly to daily
gcloud scheduler jobs update health-check-weekly \
  --schedule "0 6 * * *"
```

### Change Email Recipient
```bash
echo -n "new@example.com" | gcloud secrets versions add health-check-recipient-email --data-file=-
```

### Adjust Health Thresholds
Edit `scripts/source_health_check.py`:
```python
LOOKBACK_DAYS = 30  # Days to consider "recent"
DISCOVERY_THRESHOLD = 1  # Min articles for "healthy"
EXTRACTION_RATE_THRESHOLD = 0.8  # 80% extraction rate
FILTER_RATE_THRESHOLD = 0.3  # 30% max filter rate
```

### Add Slack Notifications
Add to `main.py`:
```python
def send_slack_alert(summary):
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if webhook_url:
        requests.post(webhook_url, json={
            "text": f"Health check: {summary['critical']} critical, {summary['warning']} warnings"
        })
```

---

## Monitoring & Operations

### View Execution History
```bash
# Last 50 executions
gcloud functions logs read weekly-source-health-check --gen2 --limit 100

# Check specific timestamp
gcloud logging read "resource.type=cloud_function AND resource.labels.function_name=weekly-source-health-check" \
  --filter="timestamp >= '2025-02-10T06:00:00Z' AND timestamp < '2025-02-10T07:00:00Z'"
```

### Archive Reports
```bash
# View all health check reports
gsutil ls -r gs://mizzou-news-crawler-reports/source_health_checks/

# Download specific report
gsutil cp gs://mizzou-news-crawler-reports/source_health_checks/20250210_060000/report.json .

# Delete old reports (retention policy can automate this)
gsutil -m rm -r gs://mizzou-news-crawler-reports/source_health_checks/*/
```

### Create Alert Policy
```bash
# Alert if function fails 2+ times in 5 minutes
gcloud alpha monitoring policies create \
  --notification-channels=CHANNEL_ID \
  --display-name="Health Check Failures" \
  --condition-display-name="2+ failures in 5 min"
```

---

## Next Steps After Deployment

1. **First Report Review**: Check email formatting, metrics accuracy
2. **Threshold Tuning**: Adjust critical/warning thresholds based on results
3. **Integration**: Add Slack webhook if desired
4. **Monitoring**: Set up alerting for critical issues
5. **Archive**: Implement retention policy on GCS backups

---

## Files Reference

**Quick Start**: [WEEKLY_HEALTH_CHECK_QUICKSTART.md](WEEKLY_HEALTH_CHECK_QUICKSTART.md)

**Full Guide**: [WEEKLY_HEALTH_CHECK_DEPLOYMENT.md](WEEKLY_HEALTH_CHECK_DEPLOYMENT.md)

**Test Script**: `python scripts/test_health_check.py`

**Cloud Function**: `gcp_functions/weekly_source_health_check/main.py`

**Diagnostic Engine**: `scripts/source_health_check.py`

---

## Summary

The weekly health check system is **production-ready** and provides:

✓ Automated source health monitoring  
✓ Formatted HTML email reports  
✓ Comprehensive metrics for 193+ sources  
✓ GCS backup and archival  
✓ Configurable schedule and thresholds  
✓ Complete deployment documentation  
✓ Test suite for validation  
✓ Easy troubleshooting and maintenance  

**Ready to deploy!** See [WEEKLY_HEALTH_CHECK_QUICKSTART.md](WEEKLY_HEALTH_CHECK_QUICKSTART.md) to get started.
