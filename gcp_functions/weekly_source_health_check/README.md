## Post-Deploy IAM Fix

Some Cloud Run deploys reset service IAM bindings. If Scheduler invocations start failing with authentication warnings, reapply these two bindings after each deploy:

1. Grant Cloud Run invoker to the Scheduler’s service account (the invoker SA used by the job):

```
gcloud run services add-iam-policy-binding weekly-source-health-check \
  --region=us-central1 \
  --member="serviceAccount:145096615031-compute@developer.gserviceaccount.com" \
  --role="roles/run.invoker"
```

2. Let Cloud Scheduler’s service agent mint OIDC tokens for that invoker service account:

```
gcloud iam service-accounts add-iam-policy-binding 145096615031-compute@developer.gserviceaccount.com \
  --member="serviceAccount:service-145096615031@gcp-sa-cloudscheduler.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountTokenCreator"
```

Or run the helper script:

```
./ensure_invoker_binding.sh us-central1 weekly-source-health-check 145096615031-compute@developer.gserviceaccount.com mizzou-news-crawler
```

# Weekly Source Health Check - Cloud Function

## Overview

This Cloud Function generates and emails a comprehensive weekly health report for all news sources in the MizzouNewsCrawler pipeline.

## Files

- **`main.py`** - Cloud Function entry point
  - `generate_html_report()` - Creates formatted HTML email body
  - `send_email_report()` - Sends email via Gmail SMTP
  - `weekly_source_health_check()` - Main HTTP handler
  
- **`requirements.txt`** - Python dependencies

## Deployment

```bash
gcloud functions deploy weekly-source-health-check \
  --gen2 \
  --runtime python311 \
  --region us-central1 \
  --source . \
  --entry-point weekly_source_health_check \
  --trigger-http \
  --memory 512MB \
  --timeout 540
```

## Configuration

### Required Secrets (Google Secret Manager)

- `news-crawler-email` - Gmail address to send from
- `news-crawler-email-password` - Gmail app-specific password (not your regular password!)
- `health-check-recipient-email` - Email address to send reports to

Create them with:
```bash
echo -n "value" | gcloud secrets create secret-name --data-file=-
```

### Required IAM Permissions

The Cloud Function's service account needs:
- `roles/secretmanager.secretAccessor` - Read secrets
- `roles/cloudsql.client` - Connect to Cloud SQL database
- `roles/storage.objectCreator` - Upload to GCS (optional)

Grant with:
```bash
gcloud secrets add-iam-policy-binding secret-name \
  --member=serviceAccount:SA_EMAIL \
  --role=roles/secretmanager.secretAccessor
```

## Execution Flow

1. HTTP request received
2. Get email configuration from Secret Manager
3. Connect to PostgreSQL database
4. Run `diagnose_source_health()` for each source (193+ sources)
5. Generate summary statistics
6. Create HTML email report with formatted table
7. Attach CSV and JSON reports
8. Send email via Gmail SMTP
9. Upload backup to GCS
10. Return success response

## Health Report Contents

### Email Summary
- Counts: Healthy / Warning / Critical / Error
- Top 20 problematic sources with issues and metrics
- HTML table format for readability

### CSV Attachment
- Spreadsheet-friendly format
- Columns: source_id, source_name, status, issues, metrics
- Easy import to Excel/Sheets for analysis

### JSON Attachment
- Raw diagnostic data
- Full metrics for each source
- Archive-friendly format

## Testing Locally

```bash
# Create local environment
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run diagnostic directly (not the Cloud Function)
python -m scripts.source_health_check
```

## Manual Testing in GCP

```bash
# Call function
gcloud functions call weekly-source-health-check --gen2 --region us-central1

# View logs
gcloud functions logs read weekly-source-health-check --gen2 --limit 50

# Check for specific errors
gcloud functions logs read weekly-source-health-check --gen2 | grep -i error
```

## Scheduled Execution

Create a Cloud Scheduler job to run this function weekly:

```bash
gcloud scheduler jobs create http health-check-weekly \
  --location us-central1 \
  --schedule "0 6 * * 1" \
  --uri https://us-central1-mizzou-news-crawler.cloudfunctions.net/weekly-source-health-check \
  --http-method GET \
  --oidc-service-account-email SA_EMAIL
```

Schedule formats (cron):
- `0 6 * * 1` = Monday 6 AM UTC
- `0 6 * * *` = Daily 6 AM UTC
- `0 */6 * * *` = Every 6 hours

## Troubleshooting

### Email not sent
- Check `gcloud functions logs` for SMTP errors
- Verify Gmail app password (not regular password)
- Confirm 2FA is enabled on Gmail account
- Verify recipient email in Secret Manager

### Database connection error
- Check Cloud SQL instance exists and is accessible
- Verify service account has `cloudsql.client` role
- Confirm Cloud SQL Connector environment variable is set
- Ensure database configuration env vars are correct:
  - `DB_NAME` (the exact PostgreSQL database name in your Cloud SQL instance)
  - `DB_USER` and `DB_PASSWORD` (credentials with access to that DB)
  - or provide a full `DATABASE_URL` (e.g., `postgresql://user:pass@/your_db_name`) which the function will parse.
  - `CLOUDSQL_INSTANCE` (connection name, e.g., `mizzou-news-crawler:us-central1:mizzou-db-prod`)

List databases (to confirm the exact name):

```bash
gcloud sql databases list --instance=mizzou-db-prod
```

Set database env vars on deploy:

```bash
gcloud functions deploy weekly-source-health-check \
  --gen2 --runtime python311 --region us-central1 \
  --source gcp_functions/weekly_source_health_check \
  --entry-point weekly_source_health_check \
  --trigger-http --memory 512MB --timeout 540 \
  --set-env-vars DB_NAME=YOUR_DB_NAME,DB_USER=YOUR_USER,CLOUDSQL_INSTANCE=mizzou-news-crawler:us-central1:mizzou-db-prod \
  --set-env-vars GMAIL_DELEGATED_USER=sender@example.com \
  --set-env-vars GMAIL_CREDENTIALS_JSON=$(cat path/to/sa.json | base64)
```

### Function timeout
- Increase timeout: `gcloud functions deploy --timeout 900`
- Check if database queries are slow
- Reduce number of sources processed

### Out of memory
- Increase memory: `gcloud functions deploy --memory 1024MB`
- Check if email attachments are too large
- Monitor actual memory usage in logs

## Performance

- **Typical runtime**: 3-5 minutes for 193 sources
- **Memory usage**: ~300-400 MB
- **Database queries**: ~2 per source (~400 total)
- **Email size**: 100-200 KB with attachments

## Cost Estimation (Monthly)

- Cloud Function invocations: ~4-5 / month = ~$0.001
- Database queries: ~500 queries / month = <$0.001
- Email via Gmail SMTP: Free (with Gmail account)
- GCS storage: ~1-2 MB / month = <$0.001

**Total estimated cost**: <$0.01/month

## Customization

### Change report frequency
Edit scheduler cron: `--schedule "0 6 * * *"` for daily

### Change email format
Edit `generate_html_report()` function for custom HTML

### Add Slack webhook
Add to `weekly_source_health_check()`:
```python
webhook_url = os.getenv("SLACK_WEBHOOK_URL")
if webhook_url:
    requests.post(webhook_url, json={"text": f"Health check: {summary}"})
```

### Adjust health thresholds
Edit `scripts/source_health_check.py`:
- `LOOKBACK_DAYS` - Change from 30 days
- Threshold constants for discovery/extraction/filter rates

### Archive reports differently
Replace/supplement GCS upload with:
- BigQuery table insert
- PostgreSQL logging table
- Custom cloud storage

## Dependencies

```
google-cloud-functions==1,<2
google-cloud-storage==2.10.0
google-cloud-secret-manager==2.16.0
sqlalchemy==2.0.23
pg8000==1.30.3
google-cloud-sql-connector==1.4.3
python-dotenv==1.0.0
```

## Related Files

- **Diagnostic engine**: `../../scripts/source_health_check.py`
- **Deployment guide**: `../../WEEKLY_HEALTH_CHECK_DEPLOYMENT.md`
- **Quick start**: `../../WEEKLY_HEALTH_CHECK_QUICKSTART.md`
- **Test script**: `../../scripts/test_health_check.py`

## Support

For issues or questions:
1. Check deployment guide for full setup instructions
2. Run test script: `python scripts/test_health_check.py`
3. Review function logs: `gcloud functions logs read weekly-source-health-check --gen2`
4. Check troubleshooting section above
