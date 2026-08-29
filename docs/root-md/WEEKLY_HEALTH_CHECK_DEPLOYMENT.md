# Weekly Source Health Check - Deployment Guide

## Overview

The weekly source health check system automatically generates comprehensive diagnostics for all news sources and emails a formatted report every week. It identifies critical issues (paused sources, discovery failures, extraction problems, high filter rates) and provides actionable metrics.

**System components:**
- `scripts/source_health_check.py` - Diagnostic engine (queries all sources, generates metrics)
- `gcp_functions/weekly_source_health_check/` - Cloud Function wrapper (runs on schedule, sends emails)
- Cloud Scheduler - Triggers function on weekly basis
- Google Secret Manager - Stores email credentials securely
- Gmail - SMTP delivery of formatted reports

---

## Prerequisites

1. **GCP Project**: `mizzou-news-crawler`
2. **Cloud Run API**: Enabled (for Cloud Functions)
3. **Secret Manager API**: Enabled
4. **Gmail Account**: Configure app-specific password for SMTP

---

## Deployment Steps

### Step 1: Set Up Email Credentials in Secret Manager

Create three secrets to store email configuration:

```bash
# Secret 1: Gmail sender address
echo -n "your-email@gmail.com" | gcloud secrets create news-crawler-email \
  --data-file=- \
  --replication-policy="automatic"

# Secret 2: Gmail app-specific password (NOT your regular password)
# Generate at: https://myaccount.google.com/apppasswords
echo -n "your-16-char-app-password" | gcloud secrets create news-crawler-email-password \
  --data-file=- \
  --replication-policy="automatic"

# Secret 3: Email recipient for reports
echo -n "your-email@example.com" | gcloud secrets create health-check-recipient-email \
  --data-file=- \
  --replication-policy="automatic"
```

**Important Notes:**
- Use a Gmail app-specific password, NOT your regular password
- Generate app password at: https://myaccount.google.com/apppasswords
- You may need to enable 2-factor authentication first

### Step 2: Create GCS Bucket for Report Backups (Optional)

```bash
# Create bucket if it doesn't exist
gsutil mb -p mizzou-news-crawler gs://mizzou-news-crawler-reports

# Optional: Set retention policy
gsutil lifecycle set - gs://mizzou-news-crawler-reports << 'EOF'
{
  "lifecycle": {
    "rule": [
      {
        "action": {"type": "Delete"},
        "condition": {"age": 90}
      }
    ]
  }
}
EOF
```

### Step 3: Deploy Cloud Function

```bash
# From workspace root
gcloud functions deploy weekly-source-health-check \
  --gen2 \
  --runtime python311 \
  --region us-central1 \
  --source gcp_functions/weekly_source_health_check \
  --entry-point weekly_source_health_check \
  --trigger-http \
  --allow-unauthenticated \
  --memory 512MB \
  --timeout 540 \
  --set-env-vars DATABASE_URL="postgresql://mizzou_user:PROD_PASSWORD@/mizzou_production" \
  --ingress-settings internal-only
```

**Configuration Explanation:**
- `--gen2`: Use Cloud Functions 2nd generation (more flexible)
- `--runtime python311`: Python 3.11 environment
- `--memory 512MB`: Sufficient for processing 193 sources
- `--timeout 540`: 9 minutes (health checks can take several minutes)
- `--allow-unauthenticated`: Cloud Scheduler will authenticate with service account
- `--ingress-settings internal-only`: Restrict to GCP internal calls

### Step 4: Create Cloud SQL Connection String

The function needs to connect to Cloud SQL. Update the `--set-env-vars` command above with the actual database connection string. For Cloud SQL Connector in Cloud Functions:

```bash
# Get connection string format
gcloud sql instances describe mizzou-db-prod-ssd --format="value(connectionName)"
# Output: mizzou-news-crawler:us-central1:mizzou-db-prod-ssd

# Update function environment variable
gcloud functions deploy weekly-source-health-check \
  --gen2 \
  --runtime python311 \
  --region us-central1 \
  --set-env-vars CLOUD_SQL_CONNECTION_NAME="mizzou-news-crawler:us-central1:mizzou-db-prod-ssd"
```

### Step 5: Grant Service Account Permissions

The Cloud Function's service account needs permissions to access secrets and database:

```bash
# Get the service account email
PROJECT_ID="mizzou-news-crawler"
SA_EMAIL="$(gcloud functions describe weekly-source-health-check \
  --gen2 --region us-central1 \
  --format='value(serviceConfig.serviceAccountEmail)')"

echo "Service Account: $SA_EMAIL"

# Grant Secret Manager access
gcloud secrets add-iam-policy-binding news-crawler-email \
  --member=serviceAccount:$SA_EMAIL \
  --role=roles/secretmanager.secretAccessor

gcloud secrets add-iam-policy-binding news-crawler-email-password \
  --member=serviceAccount:$SA_EMAIL \
  --role=roles/secretmanager.secretAccessor

gcloud secrets add-iam-policy-binding health-check-recipient-email \
  --member=serviceAccount:$SA_EMAIL \
  --role=roles/secretmanager.secretAccessor

# Grant Cloud SQL Client access (for database connection)
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member=serviceAccount:$SA_EMAIL \
  --role=roles/cloudsql.client

# Grant Storage permissions for backup uploads
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member=serviceAccount:$SA_EMAIL \
  --role=roles/storage.objectCreator
```

### Step 6: Create Cloud Scheduler Job

```bash
# Create weekly scheduler job (every Monday at 6 AM UTC)
gcloud scheduler jobs create http health-check-weekly \
  --location us-central1 \
  --schedule "0 6 * * 1" \
  --uri "https://us-central1-mizzou-news-crawler.cloudfunctions.net/weekly-source-health-check" \
  --http-method GET \
  --oidc-service-account-email $SA_EMAIL \
  --oidc-token-audience "https://us-central1-mizzou-news-crawler.cloudfunctions.net/weekly-source-health-check" \
  --message-body '{"trigger": "scheduler"}'

# Alternative: Daily checks (6 AM UTC daily)
gcloud scheduler jobs create http health-check-daily \
  --location us-central1 \
  --schedule "0 6 * * *" \
  --uri "https://us-central1-mizzou-news-crawler.cloudfunctions.net/weekly-source-health-check" \
  --http-method GET \
  --oidc-service-account-email $SA_EMAIL
```

**Schedule Format (cron):**
- `0 6 * * 1` = Weekly on Monday 6 AM UTC
- `0 6 * * *` = Daily at 6 AM UTC
- `0 */6 * * *` = Every 6 hours
- `0 3 * * 0` = Weekly on Sunday 3 AM UTC

### Step 7: Test the Deployment

```bash
# Manual trigger to verify everything works
gcloud functions call weekly-source-health-check \
  --gen2 \
  --region us-central1

# Check function logs
gcloud functions logs read weekly-source-health-check \
  --gen2 \
  --region us-central1 \
  --limit 50

# Or via Cloud Logging
gcloud logging read "resource.type=cloud_function AND resource.labels.function_name=weekly-source-health-check" \
  --limit 10 \
  --format json | jq '.[] | {timestamp: .timestamp, severity: .severity, message: .textPayload}'
```

---

## Verification Checklist

After deployment, verify:

- [ ] Cloud Function deployed successfully (`gcloud functions describe weekly-source-health-check --gen2`)
- [ ] Secrets created in Secret Manager (visible in Console or `gcloud secrets list`)
- [ ] Service account has required permissions (check IAM)
- [ ] Manual function invocation succeeds (check logs for completion)
- [ ] Email received at recipient address with:
  - Summary metrics (healthy/warning/critical counts)
  - List of problematic sources
  - CSV attachment with full data
  - JSON attachment with raw metrics
- [ ] GCS backup uploaded to `gs://mizzou-news-crawler-reports/source_health_checks/TIMESTAMP/`

---

## Health Check Report Contents

### Email Summary Section
- **Healthy Count**: Sources with no issues detected
- **Warning Count**: Sources with potential problems (discovery slowdown, high filter rates)
- **Critical Count**: Sources with severe issues (paused, no recent activity, extraction failing)

### Problematic Sources Table
Shows top 20 sources with issues:
- **Source Name**: Canonical name from database
- **Status**: critical/warning/healthy
- **Issues**: Specific problems detected
- **Recent Discoveries**: Articles found in past 30 days
- **Extraction Rate**: Percentage of discovered articles successfully extracted
- **Filter Rate**: Percentage filtered as non-news (obituary/opinion/not_article)

### Attachment: CSV Report
Spreadsheet-friendly format with columns:
- `source_id`, `source_name`, `status`, `issues`
- `database_status`, `rss_consecutive_failures`, `paused_at`
- `total_discovered`, `recent_discoveries`, `discovery_rate`
- `total_extracted`, `recent_extracted`, `extraction_rate`
- `total_filtered`, `recent_filtered`, `filter_rate`

### Attachment: JSON Report
Complete raw data including:
- Timestamp of report generation
- Summary statistics
- Per-source diagnostics with all metrics
- Issue categorization

---

## Troubleshooting

### Function Not Triggering

```bash
# Check scheduler job status
gcloud scheduler jobs describe health-check-weekly --location us-central1

# View scheduler execution logs
gcloud scheduler jobs describe health-check-weekly --location us-central1 --format='value(userUpdateTime)'

# Check Cloud Logging for scheduler errors
gcloud logging read "resource.type=cloud_scheduler_job AND resource.labels.job_id=health-check-weekly"
```

### Email Not Received

1. Check function logs for Gmail API send:
  ```bash
  gcloud functions logs read weekly-source-health-check --gen2 | grep -i "Gmail API"
  ```

2. Verify Gmail API environment:
  - `GMAIL_DELEGATED_USER` is set to the sender identity
  - `GMAIL_CREDENTIALS_JSON` contains a base64-encoded service account JSON
  - The service account has domain-wide delegation with `gmail.send` scope

3. Confirm recipient resolution:
  - Prefer `REPORT_TO_EMAIL`, else Secret `health-check-recipient-email`, else `HEALTH_CHECK_EMAIL`

Note: SMTP/app passwords are no longer used. The system sends via Gmail API (service account delegation), consistent with other report functions.

### Database Connection Failure

1. Check Cloud SQL connection:
   ```bash
   gcloud sql connect mizzou-db-prod-ssd --user mizzou_user
   ```

2. Verify service account has `cloudsql.client` role:
   ```bash
   gcloud projects get-iam-policy mizzou-news-crawler \
     --flatten="bindings[].members" \
     --filter="bindings.members:$SA_EMAIL"
   ```

3. Check Cloud SQL Auth proxy logs (if running):
   ```bash
   gcloud logging read "resource.type=cloud_sql_database AND severity=ERROR" --limit 5
   ```

### Out of Memory

If function times out or fails with memory error:
- Increase memory: `gcloud functions deploy --memory 1024MB`
- Reduce lookback window in source_health_check.py
- Split health checks into batches per region

---

## Customization

### Change Report Frequency

Edit Cloud Scheduler cron expression:
```bash
gcloud scheduler jobs update health-check-weekly \
  --location us-central1 \
  --schedule "0 3 * * 0"  # Change to Sunday 3 AM UTC
```

### Change Report Recipient

Update secret in Secret Manager:
```bash
echo -n "new-recipient@example.com" | gcloud secrets versions add health-check-recipient-email \
  --data-file=-
```

### Adjust Health Check Thresholds

Edit `scripts/source_health_check.py`:
- `LOOKBACK_DAYS`: Change from 30 days (line ~40)
- `DISCOVERY_THRESHOLD`: Minimum recent discoveries for "healthy" status
- `EXTRACTION_RATE_THRESHOLD`: Minimum extraction success rate

### Add Slack Notifications

Modify `gcp_functions/weekly_source_health_check/main.py` to also send Slack:
```python
def send_slack_alert(critical_count, warning_count):
    import requests
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if webhook_url:
        requests.post(webhook_url, json={
            "text": f"Source Health Report: {critical_count} critical, {warning_count} warnings"
        })
```

---

## Monitoring & Alerting

### View All Execution History

```bash
# Last 30 days of function executions
gcloud functions logs read weekly-source-health-check --gen2 --limit 100 | head -50
```

### Create Alert Policy (Optional)

```bash
# Alert if function fails
gcloud alpha monitoring policies create \
  --notification-channels=CHANNEL_ID \
  --display-name="Health Check Function Failures" \
  --condition-display-name="Function execution error" \
  --condition-threshold-value=1 \
  --condition-threshold-duration=300s
```

### Archive Reports

Reports are automatically uploaded to GCS. View them:
```bash
gsutil ls gs://mizzou-news-crawler-reports/source_health_checks/
gsutil cat gs://mizzou-news-crawler-reports/source_health_checks/20250202_060000/report.json | jq .
```

---

## Next Steps

1. **Deploy** using the steps above
2. **Test** by manually invoking the function
3. **Verify** email arrives at recipient with correct format
4. **Monitor** for issues in Cloud Logging
5. **Adjust** thresholds based on first report results

For questions or issues, check the troubleshooting section or consult the source code comments in:
- `scripts/source_health_check.py` - Diagnostic logic
- `gcp_functions/weekly_source_health_check/main.py` - Cloud Function wrapper
