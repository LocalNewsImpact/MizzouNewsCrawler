#!/bin/bash
set -euo pipefail

#######################################################################
# Setup ci-cd-lab namespace with all required resources
#
# This script ensures the lab namespace has:
# - Service account with Workload Identity binding
# - All necessary secrets copied from production
# - Proper IAM permissions
#######################################################################

NAMESPACE="ci-cd-lab"
PRODUCTION_NAMESPACE="production"
GCP_SA="mizzou-k8s-sa@mizzou-news-crawler.iam.gserviceaccount.com"
PROJECT_ID="mizzou-news-crawler"

echo "=========================================="
echo "Setting up ${NAMESPACE} namespace"
echo "=========================================="
echo ""

# 1. Create namespace if it doesn't exist
echo "1. Ensuring namespace exists..."
if ! kubectl get namespace ${NAMESPACE} &>/dev/null; then
    kubectl create namespace ${NAMESPACE}
    echo "✓ Created namespace ${NAMESPACE}"
else
    echo "✓ Namespace ${NAMESPACE} already exists"
fi
echo ""

# 2. Create service account
echo "2. Setting up Kubernetes service account..."
if ! kubectl get serviceaccount mizzou-app -n ${NAMESPACE} &>/dev/null; then
    kubectl create serviceaccount mizzou-app -n ${NAMESPACE}
    echo "✓ Created service account mizzou-app"
else
    echo "✓ Service account mizzou-app already exists"
fi

# Annotate with GCP service account for Workload Identity
kubectl annotate serviceaccount mizzou-app -n ${NAMESPACE} \
    iam.gke.io/gcp-service-account=${GCP_SA} \
    --overwrite
echo "✓ Annotated service account with Workload Identity"
echo ""

# 3. Add Workload Identity IAM binding
echo "3. Configuring Workload Identity IAM binding..."
gcloud iam service-accounts add-iam-policy-binding ${GCP_SA} \
    --role roles/iam.workloadIdentityUser \
    --member "serviceAccount:${PROJECT_ID}.svc.id.goog[${NAMESPACE}/mizzou-app]" \
    --project ${PROJECT_ID}
echo "✓ Added Workload Identity binding"
echo ""

# 4. Copy secrets from production
echo "4. Copying secrets from production..."

# CloudSQL credentials
if ! kubectl get secret cloudsql-db-credentials -n ${NAMESPACE} &>/dev/null; then
    kubectl get secret cloudsql-db-credentials -n ${PRODUCTION_NAMESPACE} -o yaml | \
        sed "s/namespace: ${PRODUCTION_NAMESPACE}/namespace: ${NAMESPACE}/" | \
        kubectl apply -f -
    echo "✓ Copied cloudsql-db-credentials"
else
    echo "✓ Secret cloudsql-db-credentials already exists"
fi

# Origin proxy credentials
if ! kubectl get secret origin-proxy-credentials -n ${NAMESPACE} &>/dev/null; then
    kubectl get secret origin-proxy-credentials -n ${PRODUCTION_NAMESPACE} -o yaml | \
        sed "s/namespace: ${PRODUCTION_NAMESPACE}/namespace: ${NAMESPACE}/" | \
        kubectl apply -f -
    echo "✓ Copied origin-proxy-credentials"
else
    echo "✓ Secret origin-proxy-credentials already exists"
fi
echo ""

# 5. Verify priority classes exist (cluster-wide resources)
echo "5. Verifying priority classes..."
if kubectl get priorityclass service-standard &>/dev/null; then
    echo "✓ Priority class service-standard exists"
else
    echo "⚠️  Priority class service-standard not found"
fi

if kubectl get priorityclass service-critical &>/dev/null; then
    echo "✓ Priority class service-critical exists"
else
    echo "⚠️  Priority class service-critical not found"
fi
echo ""

echo "=========================================="
echo "✅ Lab namespace setup complete"
echo "=========================================="
echo ""
echo "Namespace: ${NAMESPACE}"
echo "Service Account: mizzou-app"
echo "GCP Service Account: ${GCP_SA}"
echo "Workload Identity: Enabled"
echo ""
echo "Ready for Cloud Deploy rollouts to ${NAMESPACE}"
