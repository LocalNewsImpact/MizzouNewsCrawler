# Daily Report Cloud Function

Sends automated daily email reports with BigQuery statistics using Gmail API (free).

## Setup

### 1. Enable Gmail API

```bash
gcloud services enable gmail.googleapis.com
```

### 2. Create Service Account with Domain-Wide Delegation

```bash
# Create service account
gcloud iam service-accounts create gmail-reporter \
    --display-name="Daily Report Gmail Sender"

# Get service account email
SA_EMAIL=$(gcloud iam service-accounts list --filter="displayName:Daily Report Gmail Sender" --format='value(email)')

echo "Service account: $SA_EMAIL"
```

### 3. Configure Domain-Wide Delegation (Google Workspace Admin)

If using Google Workspace:

1. Go to [Google Workspace Admin Console](https://admin.google.com)
2. Security → API Controls → Domain-wide Delegation
3. Add new:
   - Client ID: Get from service account details
   - OAuth Scopes: `https://www.googleapis.com/auth/gmail.send`

If using personal Gmail, skip this and use OAuth2 instead (see Alternative Setup below).

### 4. Deploy the function

```bash
./scripts/deploy-daily-report.sh
```

### 5. Configure credentials

```bash
# Download service account key
gcloud iam service-accounts keys create gmail-key.json \
    --iam-account=$SA_EMAIL

# Base64 encode and set as secret
cat gmail-key.json | base64 | gcloud secrets create gmail-credentials --data-file=-

# Update function to use secret
gcloud functions deploy mizzou-daily-report \
    --region=us-central1 \
    --gen2 \
    --update-secrets=GMAIL_CREDENTIALS_JSON=gmail-credentials:latest

# Clean up local key file
rm gmail-key.json
```

### 6. Configure email addresses

```bash
gcloud functions deploy mizzou-daily-report \
    --region=us-central1 \
    --gen2 \
    --update-env-vars=GMAIL_DELEGATED_USER=your-email@yourdomain.com,REPORT_TO_EMAIL=recipient@example.com
```

For multiple recipients:

```bash
--update-env-vars=REPORT_TO_EMAIL=user1@example.com,user2@example.com
```

### 7. Create Cloud Scheduler job (daily at 6 AM Central)

```bash
# Get function URL
FUNCTION_URL=$(gcloud functions describe mizzou-daily-report --region=us-central1 --gen2 --format='value(serviceConfig.uri)')

# Get project number
PROJECT_NUMBER=$(gcloud projects describe $(gcloud config get-value project) --format='value(projectNumber)')

# Create scheduler job
gcloud scheduler jobs create http mizzou-daily-report-daily \
    --schedule='0 6 * * *' \
    --uri="$FUNCTION_URL" \
    --http-method=POST \
    --oidc-service-account-email=${PROJECT_NUMBER}-compute@developer.gserviceaccount.com \
    --time-zone='America/Chicago' \
    --location=us-central1
```

## Testing

### Manual trigger via gcloud

```bash
gcloud scheduler jobs run mizzou-daily-report-daily --location=us-central1
```

### Manual trigger via curl

```bash
FUNCTION_URL=$(gcloud functions describe mizzou-daily-report --region=us-central1 --gen2 --format='value(serviceConfig.uri)')
TOKEN=$(gcloud auth print-identity-token)

curl -X POST "$FUNCTION_URL" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json"
```

## Email Report Contents

The daily email includes:

1. **Overall Statistics**
   - Total articles in database
   - Total sources
   - Counties covered

2. **Yesterday's Articles**
   - Breakdown by source
   - County assignment
   - Unique authors per source

3. **Last 7 Days Summary**
   - Articles by county
   - Number of sources per county
   - Unique authors per county

## Configuration

Environment variables:

- `GMAIL_CREDENTIALS_JSON` (secret): Service account JSON (base64)
- `GMAIL_DELEGATED_USER`: Email to send from
- `REPORT_TO_EMAIL`: Recipient email(s), comma-separated
- `BQ_PROJECT_ID`: BigQuery project ID (auto-set)
- `BQ_DATASET`: BigQuery dataset name (default: `mizzou_news`)

## Alternative: Personal Gmail (No Workspace)

If you don't have Google Workspace, use personal Gmail with OAuth2:

1. Create OAuth2 credentials at [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Download client secret JSON
3. Use `google-auth-oauthlib` to get refresh token
4. Store refresh token as secret and modify function to use OAuth2 flow

## Troubleshooting

Check function logs:
```bash
gcloud functions logs read mizzou-daily-report --region=us-central1 --gen2 --limit=50
```

Check scheduler job status:
```bash
gcloud scheduler jobs describe mizzou-daily-report-daily --location=us-central1
```

View recent scheduler executions:
```bash
gcloud logging read "resource.type=cloud_scheduler_job AND resource.labels.job_id=mizzou-daily-report-daily" --limit=10 --format=json
```
