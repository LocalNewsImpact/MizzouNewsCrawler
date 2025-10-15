#!/bin/bash
# Phase 1 Deployment - Quick Start Script
# PR #78 Orchestration Refactor
# Date: October 15, 2025

set -e  # Exit on error

echo "🚀 Phase 1 Deployment - PR #78 Orchestration Refactor"
echo "===================================================="
echo ""
echo "⚠️  IMPORTANT: This script will deploy changes that disable discovery/extraction."
echo "    The processor will only handle cleaning, ML analysis, and entity extraction."
echo ""
read -p "Continue? (yes/no): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo "Deployment cancelled."
    exit 0
fi

echo ""
echo "📊 Step 1: Establish Baseline Metrics"
echo "======================================"
echo ""
echo "Please run these SQL queries manually and record the results:"
echo ""
echo "-- Count articles by status"
echo "SELECT status, COUNT(*) as count"
echo "FROM articles"
echo "GROUP BY status"
echo "ORDER BY count DESC;"
echo ""
echo "-- Count candidate links by status"
echo "SELECT status, COUNT(*) as count"
echo "FROM candidate_links"
echo "GROUP BY status"
echo "ORDER BY count DESC;"
echo ""
echo "-- Recent extraction rate (last 24 hours)"
echo "SELECT DATE_TRUNC('hour', created_at) as hour, COUNT(*) as articles_created"
echo "FROM articles"
echo "WHERE created_at > NOW() - INTERVAL '24 hours'"
echo "GROUP BY hour"
echo "ORDER BY hour DESC;"
echo ""
read -p "Baseline metrics recorded? (yes/no): " METRICS_DONE
if [ "$METRICS_DONE" != "yes" ]; then
    echo "Please record baseline metrics before proceeding."
    exit 1
fi

echo ""
echo "✅ Baseline metrics recorded"
echo ""

echo "🔀 Step 2: Merge PR #78"
echo "======================="
echo ""

# Check if we're in the right directory
if [ ! -f "orchestration/continuous_processor.py" ]; then
    echo "❌ Error: Please run this script from the MizzouNewsCrawler-Scripts directory"
    exit 1
fi

# Check current branch
CURRENT_BRANCH=$(git branch --show-current)
echo "Current branch: $CURRENT_BRANCH"

if [ "$CURRENT_BRANCH" != "feature/gcp-kubernetes-deployment" ]; then
    echo "Switching to feature/gcp-kubernetes-deployment..."
    git checkout feature/gcp-kubernetes-deployment
fi

echo "Pulling latest changes..."
git pull origin feature/gcp-kubernetes-deployment

echo "Fetching PR branch..."
git fetch origin copilot/refactor-pipeline-orchestration

echo ""
echo "⚠️  About to merge copilot/refactor-pipeline-orchestration"
echo "   This will add feature flags to continuous_processor.py"
echo ""
read -p "Proceed with merge? (yes/no): " MERGE_CONFIRM
if [ "$MERGE_CONFIRM" != "yes" ]; then
    echo "Merge cancelled."
    exit 1
fi

echo "Merging PR #78..."
git merge origin/copilot/refactor-pipeline-orchestration --no-ff -m "Merge PR #78: Refactor orchestration - Split dataset jobs from continuous processor

Closes #77

This merge introduces feature flags to split external site interaction (discovery,
verification, extraction) from internal processing (cleaning, ML analysis, entity extraction).

Phase 1: External steps disabled by default in processor-deployment.yaml.
External steps will be migrated to dataset-specific jobs in subsequent phases."

# Check merge status
if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Merge conflicts detected. Please resolve manually:"
    echo "   1. Resolve conflicts in the affected files"
    echo "   2. git add <resolved-files>"
    echo "   3. git commit"
    echo "   4. Run this script again starting from Step 3"
    exit 1
fi

echo "✅ Merge successful"

echo ""
echo "🧪 Running tests..."
python -m pytest tests/test_continuous_processor.py -v

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Tests failed. Please investigate before proceeding."
    echo "   Review test output and fix any issues."
    exit 1
fi

echo "✅ All tests passing"

echo ""
echo "Pushing merged changes..."
git push origin feature/gcp-kubernetes-deployment

echo ""
echo "✅ PR #78 merged successfully"
echo ""

echo "🏗️  Step 3: Build Processor Image"
echo "================================="
echo ""
read -p "Trigger Cloud Build for processor? (yes/no): " BUILD_CONFIRM
if [ "$BUILD_CONFIRM" != "yes" ]; then
    echo "Build skipped. Please trigger manually:"
    echo "   gcloud builds triggers run build-processor-manual --branch=feature/gcp-kubernetes-deployment"
    exit 0
fi

echo "Triggering Cloud Build..."
gcloud builds triggers run build-processor-manual \
  --branch=feature/gcp-kubernetes-deployment

# Get build ID
BUILD_ID=$(gcloud builds list --filter="trigger_id=build-processor-manual" --limit=1 --format="value(id)")
echo ""
echo "Build triggered: $BUILD_ID"
echo "Monitor at: https://console.cloud.google.com/cloud-build/builds/$BUILD_ID?project=mizzou-news-crawler"
echo ""

echo "Streaming build logs..."
gcloud builds log $BUILD_ID --stream

# Check build status
BUILD_STATUS=$(gcloud builds describe $BUILD_ID --format="value(status)")
if [ "$BUILD_STATUS" != "SUCCESS" ]; then
    echo ""
    echo "❌ Build failed with status: $BUILD_STATUS"
    echo "   Review build logs and investigate errors."
    exit 1
fi

echo ""
echo "✅ Build successful"
echo ""

echo "📦 Step 4: Verify Image"
echo "======================="
echo ""

echo "Listing recent processor images..."
gcloud artifacts docker images list \
  us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor \
  --limit=5 \
  --sort-by=~CREATE_TIME \
  --format="table(package,version,createTime)"

# Get latest image SHA
NEW_IMAGE_SHA=$(gcloud artifacts docker images list \
  us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor \
  --limit=1 \
  --sort-by=~CREATE_TIME \
  --format="value(version)")

echo ""
echo "✅ New processor image: processor:$NEW_IMAGE_SHA"
echo ""

echo "⚠️  MANUAL STEP REQUIRED"
echo "======================="
echo ""
echo "Before deploying, update k8s/processor-deployment.yaml:"
echo "1. Open k8s/processor-deployment.yaml"
echo "2. Update line 32 (image:) to:"
echo "   image: us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:$NEW_IMAGE_SHA"
echo "3. Verify feature flags (lines 85-96) are set correctly:"
echo "   - ENABLE_DISCOVERY: false"
echo "   - ENABLE_VERIFICATION: false"
echo "   - ENABLE_EXTRACTION: false"
echo "   - ENABLE_CLEANING: true"
echo "   - ENABLE_ML_ANALYSIS: true"
echo "   - ENABLE_ENTITY_EXTRACTION: true"
echo ""
read -p "Image updated in deployment YAML? (yes/no): " YAML_UPDATED
if [ "$YAML_UPDATED" != "yes" ]; then
    echo "Please update the YAML file before deploying."
    exit 1
fi

echo ""
echo "🚀 Step 5: Deploy to Production"
echo "==============================="
echo ""

# Get current processor status
echo "Current processor status:"
kubectl get pods -n production -l app=mizzou-processor
echo ""

CURRENT_IMAGE=$(kubectl get deployment mizzou-processor -n production -o jsonpath='{.spec.template.spec.containers[0].image}')
echo "Current image: $CURRENT_IMAGE"
echo "New image: us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:$NEW_IMAGE_SHA"
echo ""

read -p "Deploy new processor image? (yes/no): " DEPLOY_CONFIRM
if [ "$DEPLOY_CONFIRM" != "yes" ]; then
    echo "Deployment cancelled."
    echo ""
    echo "To deploy manually:"
    echo "   kubectl apply -f k8s/processor-deployment.yaml"
    exit 0
fi

echo "Applying deployment..."
kubectl apply -f k8s/processor-deployment.yaml

echo ""
echo "Watching rollout (timeout: 5 minutes)..."
kubectl rollout status deployment/mizzou-processor -n production --timeout=5m

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Rollout failed or timed out"
    echo "   Check pod status: kubectl get pods -n production -l app=mizzou-processor"
    echo "   Check logs: kubectl logs -n production -l app=mizzou-processor --tail=100"
    exit 1
fi

echo ""
echo "✅ Deployment successful"
echo ""

echo "🔍 Step 6: Validate Feature Flags"
echo "=================================="
echo ""

echo "Checking processor logs for feature flag status..."
sleep 10  # Wait for pod to initialize

kubectl logs -n production -l app=mizzou-processor --tail=200 | grep -A 10 "Enabled pipeline steps" || {
    echo ""
    echo "⚠️  Could not find feature flag status in logs"
    echo "   Checking full logs..."
    kubectl logs -n production -l app=mizzou-processor --tail=100
}

echo ""
echo "📊 Monitoring work queue..."
echo ""
kubectl logs -n production -l app=mizzou-processor --tail=50

echo ""
echo "✅ Phase 1 Deployment Complete"
echo "=============================="
echo ""
echo "Next Steps:"
echo "1. Monitor processor logs for 24 hours:"
echo "   kubectl logs -n production -l app=mizzou-processor --follow"
echo ""
echo "2. Run validation tests (see PHASE1_DEPLOYMENT_TRACKER.md)"
echo ""
echo "3. Complete Phase 1 report and make GO/NO-GO decision for Phase 2"
echo ""
echo "📝 Update PHASE1_DEPLOYMENT_TRACKER.md with:"
echo "   - Merge completed: YES at $(date)"
echo "   - Build ID: $BUILD_ID"
echo "   - Image deployed: processor:$NEW_IMAGE_SHA"
echo "   - Rollout completed: YES at $(date)"
echo ""
echo "⚠️  Remember: No new articles will be extracted during Phase 1."
echo "   This is expected behavior. Phase 2 will restore extraction via Mizzou jobs."
echo ""
