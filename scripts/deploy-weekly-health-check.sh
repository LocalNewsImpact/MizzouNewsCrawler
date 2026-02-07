#!/bin/bash
# Deploy weekly health check Cloud Function using existing Gmail infrastructure

set -e

FUNCTION_NAME="mizzou-weekly-health-check"
REGION="us-central1"
PROJECT_ID=$(gcloud config get-value project)

# Get the Gmail credentials secret (already created for daily report)
GMAIL_SECRET_NAME="gmail-credentials"

echo "Deploying Cloud Function: $FUNCTION_NAME"

gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime=python311 \
    --region=$REGION \
    --source=gcp/functions/weekly-health-check \
    --entry-point=send_weekly_health_check \
    --trigger-http \
    --no-allow-unauthenticated \
    --timeout=600s \
    --memory=512MB \
    --set-env-vars="BQ_PROJECT_ID=$PROJECT_ID" \
    --update-secrets="GMAIL_CREDENTIALS_JSON=$GMAIL_SECRET_NAME:latest"

# Get function details
FUNCTION_URL=$(gcloud functions describe $FUNCTION_NAME --region=$REGION --gen2 --format='value(serviceConfig.uri)')
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
SERVICE_ACCOUNT="$PROJECT_NUMBER-compute@developer.gserviceaccount.com"

echo ""
echo "Cloud Function deployed successfully!"
echo "Function URL: $FUNCTION_URL"
echo ""
echo "Existing configuration from daily-report:"
echo "  - Gmail Credentials: Using existing gmail-credentials secret"
echo "  - Gmail Delegated User: Set via GMAIL_DELEGATED_USER env var"
echo "  - Report Recipient: Set via REPORT_TO_EMAIL env var"
echo ""
echo "Next steps:"
echo ""
echo "1. Copy environment variables from daily-report function:"
echo "   gcloud functions describe mizzou-daily-report --region=$REGION --gen2 --format=json | jq '.serviceConfig.environmentVariables'"
echo ""
echo "2. Apply same environment variables to health check:"
echo "   gcloud functions deploy $FUNCTION_NAME \\"
echo "     --region=$REGION --gen2 \\"
echo "     --update-env-vars=GMAIL_DELEGATED_USER=chair@localnewsimpact.org,REPORT_TO_EMAIL=recipient@example.com,MIZZOU_DB_PASSWORD=password"
echo ""
echo "3. Grant service account access to Cloud SQL:"
echo "   gcloud projects add-iam-policy-binding $PROJECT_ID \\"
echo "     --member=serviceAccount:$SERVICE_ACCOUNT \\"
echo "     --role=roles/cloudsql.client"
echo ""
echo "4. Create Cloud Scheduler job (runs every Monday 6 AM UTC):"
echo "   gcloud scheduler jobs create http health-check-weekly \\"
echo "     --location=$REGION \\"
echo "     --schedule='0 6 * * 1' \\"
echo "     --uri='$FUNCTION_URL' \\"
echo "     --http-method=GET \\"
echo "     --oidc-service-account-email=$SERVICE_ACCOUNT"
echo ""
echo "5. Test the function:"
echo "   gcloud functions call $FUNCTION_NAME --region=$REGION --gen2"
