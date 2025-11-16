#!/bin/bash
# Deploy daily report Cloud Function

set -e

FUNCTION_NAME="mizzou-daily-report"
REGION="us-central1"
PROJECT_ID=$(gcloud config get-value project)
GMAIL_ACCOUNT="chair@localnewsimpact.org"

echo "Deploying Cloud Function: $FUNCTION_NAME"

gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime=python311 \
    --region=$REGION \
    --source=gcp/functions/daily-report \
    --entry-point=send_daily_report \
    --trigger-http \
    --no-allow-unauthenticated \
    --set-env-vars="BQ_PROJECT_ID=$PROJECT_ID,BQ_DATASET=mizzou_news,GMAIL_DELEGATED_USER=$GMAIL_ACCOUNT" \
    --timeout=540s \
    --memory=512MB

FUNCTION_URL=$(gcloud functions describe $FUNCTION_NAME --region=$REGION --gen2 --format='value(serviceConfig.uri)')
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')

echo ""
echo "Cloud Function deployed successfully!"
echo "Function URL: $FUNCTION_URL"
echo ""
echo "Next steps:"
echo ""
echo "1. Create service account and credentials:"
echo "   gcloud iam service-accounts create gmail-reporter --display-name='Daily Report Gmail Sender'"
echo "   SA_EMAIL=\$(gcloud iam service-accounts list --filter='displayName:Daily Report Gmail Sender' --format='value(email)')"
echo "   gcloud iam service-accounts keys create /tmp/gmail-key.json --iam-account=\$SA_EMAIL"
echo ""
echo "2. Configure Google Workspace delegation for chair@localnewsimpact.org:"
echo "   - Go to: https://admin.google.com/ac/owl/domainwidedelegation"
echo "   - Add Client ID from service account"
echo "   - OAuth Scope: https://www.googleapis.com/auth/gmail.send"
echo ""
echo "3. Store credentials as secret:"
echo "   cat /tmp/gmail-key.json | base64 | gcloud secrets create gmail-credentials --data-file=-"
echo "   gcloud functions deploy $FUNCTION_NAME --region=$REGION --gen2 --update-secrets=GMAIL_CREDENTIALS_JSON=gmail-credentials:latest"
echo "   rm /tmp/gmail-key.json"
echo ""
echo "4. Set recipient email:"
echo "   gcloud functions deploy $FUNCTION_NAME --region=$REGION --gen2 --update-env-vars=REPORT_TO_EMAIL=your-email@example.com"
echo ""
echo "5. Create Cloud Scheduler job (daily at 6 AM Central):"
echo "   gcloud scheduler jobs create http ${FUNCTION_NAME}-daily \\"
echo "     --schedule='0 6 * * *' \\"
echo "     --uri='$FUNCTION_URL' \\"
echo "     --http-method=POST \\"
echo "     --oidc-service-account-email=$PROJECT_NUMBER-compute@developer.gserviceaccount.com \\"
echo "     --time-zone='America/Chicago' \\"
echo "     --location=$REGION"
echo ""
echo "6. Test manually:"
echo "   gcloud scheduler jobs run ${FUNCTION_NAME}-daily --location=$REGION"
