#!/bin/bash
# Deploy Cloud SQL Connector-enabled services to GKE
# This script applies the updated Kubernetes manifests with v1.2.0 images

set -e

echo "🚀 Deploying Cloud SQL Connector-enabled services..."
echo ""

# Check if builds are complete
echo "Checking build status..."
gcloud builds list --limit=3 --format="table(id,status,images[0])"
echo ""

read -p "Are all builds SUCCESS? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]
then
    echo "❌ Please wait for builds to complete before deploying"
    exit 1
fi

echo "1️⃣  Applying updated CronJobs..."
kubectl apply -f k8s/crawler-cronjob.yaml -n production
kubectl apply -f k8s/processor-cronjob.yaml -n production
echo "✅ CronJobs updated"
echo ""

echo "2️⃣  Applying updated API Deployment (rolling update)..."
kubectl apply -f k8s/api-deployment.yaml -n production
echo "✅ API Deployment updated"
echo ""

echo "3️⃣  Waiting for API rollout to complete..."
kubectl rollout status deployment/mizzou-api -n production --timeout=5m
echo "✅ API rollout complete"
echo ""

echo "4️⃣  Verifying pods are running..."
kubectl get pods -n production -l app=mizzou-api
echo ""

echo "5️⃣  Checking API pod logs for Cloud SQL connector..."
API_POD=$(kubectl get pods -n production -l app=mizzou-api -o jsonpath='{.items[0].metadata.name}')
echo "API Pod: $API_POD"
kubectl logs -n production $API_POD --tail=20 | grep -i "cloud\|sql\|connect" || echo "(No connector logs yet - that's normal)"
echo ""

echo "✅ Deployment complete!"
echo ""
echo "📊 Next steps:"
echo "  - Create a test crawler job: kubectl create job --from=cronjob/mizzou-crawler test-connector -n production"
echo "  - Monitor job: kubectl get jobs -n production -w"
echo "  - Verify job completes automatically (no manual cleanup needed!)"
echo "  - Check logs: kubectl logs -n production job/test-connector"
