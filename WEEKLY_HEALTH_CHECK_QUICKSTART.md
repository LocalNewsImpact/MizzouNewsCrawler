# Weekly Health Check - Quick Start

## One-Command Setup (if you have all secrets created)

```bash
# 1. Create secrets
echo -n "your-email@gmail.com" | gcloud secrets create news-crawler-email --data-file=- --replication-policy=automatic
echo -n "app-password-16-chars" | gcloud secrets create news-crawler-email-password --data-file=- --replication-policy=automatic
echo -n "recipient@example.com" | gcloud secrets create health-check-recipient-email --data-file=- --replication-policy=automatic

# 2. Get service account
PROJECT_ID="mizzou-news-crawler"
SA_EMAIL="$(gcloud functions describe weekly-source-health-check --gen2 --region us-central1 --format='value(serviceConfig.serviceAccountEmail)' 2>/dev/null || echo '')"

# 3. If function doesn't exist yet, grant IAM first:
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member=serviceAccount:$(gcloud config get-value project)-compute@developer.gserviceaccount.com \
  --role=roles/cloudsql.client

# 4. Deploy function
gcloud functions deploy weekly-source-health-check \
  --gen2 --runtime python311 --region us-central1 \
  --source gcp_functions/weekly_source_health_check \
  --entry-point weekly_source_health_check \
  --trigger-http --allow-unauthenticated --memory 512MB --timeout 540

# 5. Grant permissions to new service account
SA_EMAIL="$(gcloud functions describe weekly-source-health-check --gen2 --region us-central1 --format='value(serviceConfig.serviceAccountEmail)')"

for SECRET in news-crawler-email news-crawler-email-password health-check-recipient-email; do
  gcloud secrets add-iam-policy-binding $SECRET \
    --member=serviceAccount:$SA_EMAIL \
    --role=roles/secretmanager.secretAccessor
done

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member=serviceAccount:$SA_EMAIL \
  --role=roles/cloudsql.client

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member=serviceAccount:$SA_EMAIL \
  --role=roles/storage.objectCreator

# 6. Create scheduler (Monday 6 AM UTC)
gcloud scheduler jobs create http health-check-weekly \
  --location us-central1 \
  --schedule "0 6 * * 1" \
  --uri "https://us-central1-$PROJECT_ID.cloudfunctions.net/weekly-source-health-check" \
  --http-method GET \
  --oidc-service-account-email $SA_EMAIL

# 7. Test
gcloud functions call weekly-source-health-check --gen2 --region us-central1
```

## Key Files

| File | Purpose |
|------|---------|
| `scripts/source_health_check.py` | Health diagnostic engine |
| `gcp_functions/weekly_source_health_check/main.py` | Cloud Function wrapper + email sender |
| `gcp_functions/weekly_source_health_check/requirements.txt` | Python dependencies |
| `WEEKLY_HEALTH_CHECK_DEPLOYMENT.md` | Full deployment guide |

## Email Configuration

**Gmail Setup (Required):**
1. Have 2-factor authentication enabled on Gmail account
2. Generate app-specific password at: https://myaccount.google.com/apppasswords
3. Use 16-character app password in `news-crawler-email-password` secret

## Common Commands

```bash
# Test function
gcloud functions call weekly-source-health-check --gen2 --region us-central1

# View logs
gcloud functions logs read weekly-source-health-check --gen2 --limit 50

# Manual scheduler trigger
gcloud scheduler jobs run health-check-weekly --location us-central1

# View scheduler history
gcloud scheduler jobs describe health-check-weekly --location us-central1

# View GCS backups
gsutil ls -r gs://mizzou-news-crawler-reports/source_health_checks/

# Check secrets
gcloud secrets list | grep health-check
```

## Report Features

- **HTML Email**: Formatted summary with critical/warning/healthy counts
- **Top Issues Table**: 20 most problematic sources with metrics
- **CSV Attachment**: Spreadsheet-friendly full report
- **JSON Attachment**: Raw metrics for archival
- **GCS Backup**: Automatic upload for long-term storage

## Troubleshooting

| Issue | Command |
|-------|---------|
| Email not received | `gcloud functions logs read weekly-source-health-check --gen2 \| grep -i email` |
| Function error | `gcloud functions logs read weekly-source-health-check --gen2 --limit 10` |
| Database connection fails | `kubectl exec -n production deployment/mizzou-api -- python -c "from src.models.database import DatabaseManager; db = DatabaseManager(); print(db.get_session().execute(text('SELECT 1')).scalar())"` |
| Scheduler not triggering | `gcloud scheduler jobs describe health-check-weekly --location us-central1` |

## Next: Monitor & Adjust

After first report:
- Review thresholds in `source_health_check.py` 
- Adjust `LOOKBACK_DAYS`, discovery/extraction thresholds
- Add Slack webhook if desired
- Update schedule if needed (daily vs weekly)

See `WEEKLY_HEALTH_CHECK_DEPLOYMENT.md` for full documentation.
