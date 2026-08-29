# Weekly Health Check System - Pre-Deployment Checklist

## ✓ Implementation Complete

- [x] Health diagnostic engine created (`scripts/source_health_check.py`)
- [x] Cloud Function wrapper with email delivery (`gcp_functions/weekly_source_health_check/main.py`)
- [x] Python dependencies configured (`gcp_functions/weekly_source_health_check/requirements.txt`)
- [x] HTML email template generated
- [x] CSV/JSON report export implemented
- [x] GCS backup upload configured
- [x] Error handling and logging added
- [x] Code syntax verified (no compilation errors)

---

## Pre-Deployment Checklist

### Prerequisites (Complete These First)

- [ ] Google Cloud project: `mizzou-news-crawler`
- [ ] Cloud Run API enabled: `gcloud services enable run.googleapis.com`
- [ ] Cloud Functions API enabled: `gcloud services enable cloudfunctions.googleapis.com`
- [ ] Cloud Build API enabled: `gcloud services enable cloudbuild.googleapis.com`
- [ ] Secret Manager API enabled: `gcloud services enable secretmanager.googleapis.com`
- [ ] Cloud Scheduler API enabled: `gcloud services enable cloudscheduler.googleapis.com`
- [ ] Cloud SQL instance exists: `mizzou-db-prod-ssd` in `us-central1`
- [ ] GCS bucket exists: `gs://mizzou-news-crawler-reports` (or create one)

### Gmail Setup

- [ ] Have Gmail account credentials
- [ ] Enable 2-factor authentication on Gmail account
- [ ] Generate app-specific password at: https://myaccount.google.com/apppasswords
- [ ] Save the 16-character app password (you'll need it for deployment)

### GCP Configuration

- [ ] Note the GCP project ID: `mizzou-news-crawler`
- [ ] Identify recipient email address for reports
- [ ] Verify service account `default@mizzou-news-crawler.iam.gserviceaccount.com` exists
- [ ] Confirm Cloud SQL connection name: `mizzou-news-crawler:us-central1:mizzou-db-prod-ssd`

---

## Deployment Steps

### Step 1: Create Google Secrets (5 min)

```bash
# Secret 1: Gmail sender address
echo -n "your-email@gmail.com" | gcloud secrets create news-crawler-email \
  --data-file=- \
  --replication-policy="automatic"

# Secret 2: Gmail app-specific password
echo -n "your-16-char-app-password" | gcloud secrets create news-crawler-email-password \
  --data-file=- \
  --replication-policy="automatic"

# Secret 3: Report recipient email
echo -n "recipient@example.com" | gcloud secrets create health-check-recipient-email \
  --data-file=- \
  --replication-policy="automatic"

# Verify secrets created
gcloud secrets list | grep health-check
gcloud secrets list | grep news-crawler-email
```

**Checklist:**
- [ ] `news-crawler-email` secret created
- [ ] `news-crawler-email-password` secret created  
- [ ] `health-check-recipient-email` secret created
- [ ] Secrets verified with `gcloud secrets list`

### Step 2: Deploy Cloud Function (2 min)

```bash
PROJECT_ID="mizzou-news-crawler"
REGION="us-central1"

gcloud functions deploy weekly-source-health-check \
  --gen2 \
  --runtime python311 \
  --region $REGION \
  --source gcp_functions/weekly_source_health_check \
  --entry-point weekly_source_health_check \
  --trigger-http \
  --allow-unauthenticated \
  --memory 512MB \
  --timeout 540 \
  --set-env-vars "CLOUD_SQL_CONNECTION_NAME=$PROJECT_ID:$REGION:mizzou-db-prod-ssd" \
  --ingress-settings internal-only
```

**Checklist:**
- [ ] Command executed without errors
- [ ] Function appears in Cloud Console: https://console.cloud.google.com/functions
- [ ] Function status shows "Active"

### Step 3: Grant IAM Permissions (2 min)

```bash
PROJECT_ID="mizzou-news-crawler"

# Get the service account for the function
SA_EMAIL="$(gcloud functions describe weekly-source-health-check \
  --gen2 --region us-central1 \
  --format='value(serviceConfig.serviceAccountEmail)')"

echo "Service Account: $SA_EMAIL"

# Grant Secret Manager access for all 3 secrets
for SECRET in news-crawler-email news-crawler-email-password health-check-recipient-email; do
  gcloud secrets add-iam-policy-binding $SECRET \
    --member=serviceAccount:$SA_EMAIL \
    --role=roles/secretmanager.secretAccessor
done

# Grant Cloud SQL Client role
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member=serviceAccount:$SA_EMAIL \
  --role=roles/cloudsql.client

# Grant Storage permissions for GCS uploads
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member=serviceAccount:$SA_EMAIL \
  --role=roles/storage.objectCreator
```

**Checklist:**
- [ ] Service account email printed correctly
- [ ] All IAM binding commands executed successfully
- [ ] No "Failed" messages in output

### Step 4: Create Cloud Scheduler Job (1 min)

```bash
PROJECT_ID="mizzou-news-crawler"
REGION="us-central1"

# Get service account again
SA_EMAIL="$(gcloud functions describe weekly-source-health-check \
  --gen2 --region $REGION \
  --format='value(serviceConfig.serviceAccountEmail)')"

# Create scheduler job (Monday 6 AM UTC)
gcloud scheduler jobs create http health-check-weekly \
  --location $REGION \
  --schedule "0 6 * * 1" \
  --uri "https://$REGION-$PROJECT_ID.cloudfunctions.net/weekly-source-health-check" \
  --http-method GET \
  --oidc-service-account-email $SA_EMAIL \
  --oidc-token-audience "https://$REGION-$PROJECT_ID.cloudfunctions.net/weekly-source-health-check"

# Verify job created
gcloud scheduler jobs list --location $REGION
```

**Checklist:**
- [ ] Scheduler job created successfully
- [ ] Job appears in output of `gcloud scheduler jobs list`
- [ ] Schedule shows "0 6 * * 1" (Monday 6 AM UTC)

---

## Testing

### Test 1: Manual Function Invocation (2 min)

```bash
# Call the function directly
gcloud functions call weekly-source-health-check --gen2 --region us-central1

# Expected response:
# {
#   "status": "success",
#   "message": "Health check completed and report emailed",
#   "recipient": "your-email@example.com",
#   "timestamp": "20250210_060000",
#   "summary": {
#     "healthy": 170,
#     "warning": 15,
#     "critical": 8,
#     "error": 0,
#     "total": 193
#   }
# }
```

**Checklist:**
- [ ] Function returns HTTP 200 with "success" status
- [ ] Summary shows reasonable counts (total should be ~193 sources)
- [ ] `critical` and `warning` counts are non-zero (expected)
- [ ] No error messages in response

### Test 2: Check Email Receipt (5 min)

After running the manual test:

```bash
# Check function logs for email send
gcloud functions logs read weekly-source-health-check --gen2 --limit 20

# Look for messages like:
# "Sending email report to..."
# "Email sent successfully!"
```

**Checklist:**
- [ ] Email received at recipient address
- [ ] Subject line: "Weekly Source Health Report - YYYY-MM-DD"
- [ ] Email contains:
  - [ ] Summary statistics (Healthy/Warnings/Critical counts)
  - [ ] List of critical issues (if any)
  - [ ] List of warning issues (if any)
  - [ ] Table with top 20 problematic sources
  - [ ] CSV attachment `source_health_*.csv`
  - [ ] JSON attachment `source_health_*.json`

### Test 3: Verify Scheduler Trigger

```bash
# Manual trigger of scheduler job
gcloud scheduler jobs run health-check-weekly --location us-central1

# Check if it executed
gcloud scheduler jobs describe health-check-weekly --location us-central1

# Verify execution appeared in logs
gcloud functions logs read weekly-source-health-check --gen2 --limit 20 | head -10
```

**Checklist:**
- [ ] Scheduler job executed without error
- [ ] Function was called (check logs)
- [ ] Email sent again (if test successful)

### Test 4: GCS Backup Verification

```bash
# Check if reports were uploaded to GCS
gsutil ls gs://mizzou-news-crawler-reports/source_health_checks/

# You should see a directory like: source_health_checks/20250210_060000/

# List files in that directory
gsutil ls gs://mizzou-news-crawler-reports/source_health_checks/20250210_060000/

# Should contain: report.csv and report.json
```

**Checklist:**
- [ ] GCS bucket contains `source_health_checks/` directory
- [ ] Directory contains timestamp subdirectories
- [ ] Each subdirectory contains `report.csv` and `report.json`

---

## Post-Deployment Validation

### Monitoring Setup

```bash
# View all function executions
gcloud functions logs read weekly-source-health-check --gen2 --limit 50

# Create alert for function errors (optional)
# See DEPLOYMENT.md for alert policy setup
```

### First Week Observations

- [ ] Email arrives every Monday at 6 AM UTC (or per configured schedule)
- [ ] Report format is readable and contains actionable information
- [ ] CSV/JSON attachments are present and valid
- [ ] GCS backups are created after each run
- [ ] No errors in function logs

### Review & Adjust

After first report:

- [ ] Review the identified critical/warning issues
- [ ] Verify thresholds are appropriate for your use case
- [ ] Check if any false positives need threshold adjustment
- [ ] Consider if alert conditions should be stricter/looser

---

## Troubleshooting During Testing

### Issue: Function returns HTTP 500 error

```bash
# Check the detailed error
gcloud functions logs read weekly-source-health-check --gen2 --limit 5

# Common causes:
# - Secret not accessible: Check IAM permissions (Step 3)
# - Database connection error: Check Cloud SQL connectivity
# - Memory exceeded: Increase to 1024MB
```

### Issue: Email not received

```bash
# Check for SMTP errors in logs
gcloud functions logs read weekly-source-health-check --gen2 | grep -i email

# Verify secret values are correct
gcloud secrets versions access latest --secret=news-crawler-email
# Should show: your-email@gmail.com

# Common causes:
# - Wrong app password: Regenerate at https://myaccount.google.com/apppasswords
# - 2FA not enabled on Gmail
# - Recipient email address typo
```

### Issue: Scheduler job doesn't trigger

```bash
# Check scheduler job configuration
gcloud scheduler jobs describe health-check-weekly --location us-central1

# Verify next execution time is reasonable
# If "nextScheduleTime" is far in the future, check the cron expression

# Manual test the scheduler
gcloud scheduler jobs run health-check-weekly --location us-central1
```

---

## Success Criteria

✓ **System is successfully deployed when:**

1. Cloud Function responds to HTTP calls with status 200
2. Function logs show "Email sent successfully!" 
3. Email arrives at recipient address with proper formatting
4. CSV and JSON attachments are present in email
5. GCS backup files exist at `gs://mizzou-news-crawler-reports/source_health_checks/`
6. Scheduler executes on schedule (check next execution time)
7. Health check metrics show reasonable counts (173-193 sources, some warnings/critical)

---

## Support & Documentation

**Quick Start**: [WEEKLY_HEALTH_CHECK_QUICKSTART.md](WEEKLY_HEALTH_CHECK_QUICKSTART.md)

**Full Guide**: [WEEKLY_HEALTH_CHECK_DEPLOYMENT.md](WEEKLY_HEALTH_CHECK_DEPLOYMENT.md)

**System Summary**: [WEEKLY_HEALTH_CHECK_SUMMARY.md](WEEKLY_HEALTH_CHECK_SUMMARY.md)

**Test Script**: `python scripts/test_health_check.py`

**Source Code**:
- Cloud Function: `gcp_functions/weekly_source_health_check/main.py`
- Diagnostic Engine: `scripts/source_health_check.py`

---

## Timeline

| Phase | Duration | Actions |
|-------|----------|---------|
| Prerequisites | 5 min | Enable APIs, generate Gmail app password |
| Deployment | 10 min | Create secrets, deploy function, grant IAM, create scheduler |
| Testing | 5 min | Manual function call, verify email, check logs |
| Validation | 5 min | Monitor for 1 week, collect feedback |
| **Total** | **~25 min** | Ready for production |

---

**Ready to deploy!** Start with Step 1 above. Questions? Check the troubleshooting section or refer to the full deployment guide.
