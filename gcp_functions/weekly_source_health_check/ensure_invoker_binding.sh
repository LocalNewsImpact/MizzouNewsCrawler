#!/usr/bin/env zsh
set -euo pipefail

# Ensures Cloud Run invoker and OIDC token creator bindings exist after deploy.
# Defaults are set for project mizzou-news-crawler in us-central1.
# Usage:
#   ./ensure_invoker_binding.sh [REGION] [SERVICE_NAME] [INVOKER_SA] [PROJECT_ID]
#
# Example:
#   ./ensure_invoker_binding.sh us-central1 weekly-source-health-check 145096615031-compute@developer.gserviceaccount.com mizzou-news-crawler

REGION=${1:-us-central1}
SERVICE_NAME=${2:-weekly-source-health-check}
INVOKER_SA=${3:-145096615031-compute@developer.gserviceaccount.com}
PROJECT_ID=${4:-mizzou-news-crawler}

SCHEDULER_AGENT="service-${PROJECT_ID%%-*}@gcp-sa-cloudscheduler.iam.gserviceaccount.com"
# For non-default project ID patterns, fallback to the known value
if [[ "$PROJECT_ID" == "mizzou-news-crawler" ]]; then
  SCHEDULER_AGENT="service-145096615031@gcp-sa-cloudscheduler.iam.gserviceaccount.com"
fi

print "Applying Cloud Run invoker binding to $SERVICE_NAME in $REGION for $INVOKER_SA..."
gcloud run services add-iam-policy-binding "$SERVICE_NAME" \
  --region="$REGION" \
  --member="serviceAccount:$INVOKER_SA" \
  --role="roles/run.invoker"

print "Granting Token Creator to Cloud Scheduler service agent on $INVOKER_SA..."
gcloud iam service-accounts add-iam-policy-binding "$INVOKER_SA" \
  --member="serviceAccount:$SCHEDULER_AGENT" \
  --role="roles/iam.serviceAccountTokenCreator"

print "Done."
