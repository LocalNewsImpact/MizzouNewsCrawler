#!/bin/bash
# Test script to verify BigQuery export functionality in processor image

set -e

NAMESPACE="production"
POD_NAME="test-bq-export-$$"
IMAGE="us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:latest"

echo "🧪 Testing BigQuery export in processor image..."
echo ""

# Clean up function
cleanup() {
    echo "🧹 Cleaning up test pod..."
    kubectl delete pod "$POD_NAME" -n "$NAMESPACE" --ignore-not-found=true 2>/dev/null || true
}
trap cleanup EXIT

# Test 1: Check if google-cloud-bigquery is installed
echo "📦 Test 1: Checking if google-cloud-bigquery library is installed..."
kubectl run "$POD_NAME" \
    --image="$IMAGE" \
    -n "$NAMESPACE" \
    --restart=Never \
    --rm -i \
    -- python -c "import google.cloud.bigquery; print('✅ google-cloud-bigquery is installed')" \
    2>&1 | grep -q "✅" && echo "✅ PASS: Library is installed" || echo "❌ FAIL: Library not found"

sleep 2

# Test 2: Check if bigquery_export module can be imported
echo ""
echo "📦 Test 2: Checking if bigquery_export module can be imported..."
kubectl run "$POD_NAME" \
    --image="$IMAGE" \
    -n "$NAMESPACE" \
    --restart=Never \
    --rm -i \
    -- python -c "from src.pipeline.bigquery_export import export_articles_to_bigquery; print('✅ Module imported successfully')" \
    2>&1 | grep -q "✅" && echo "✅ PASS: Module can be imported" || echo "❌ FAIL: Import failed"

sleep 2

# Test 3: Check if CLI command is available
echo ""
echo "🔧 Test 3: Checking if bigquery-export CLI command is registered..."
kubectl run "$POD_NAME" \
    --image="$IMAGE" \
    -n "$NAMESPACE" \
    --restart=Never \
    --rm -i \
    --env="USE_CLOUD_SQL_CONNECTOR=false" \
    -- python -m src.cli.main bigquery-export --help \
    2>&1 | grep -q "bigquery-export" && echo "✅ PASS: Command is available" || echo "❌ FAIL: Command not found"

sleep 2

# Test 4: Check telemetry warning is gone
echo ""
echo "📊 Test 4: Checking if telemetry SQLite warning is fixed..."
OUTPUT=$(kubectl run "$POD_NAME" \
    --image="$IMAGE" \
    -n "$NAMESPACE" \
    --restart=Never \
    --rm -i \
    --env="USE_CLOUD_SQL_CONNECTOR=true" \
    --env="CLOUD_SQL_INSTANCE=mizzou-news-crawler:us-central1:mizzou-db-prod" \
    --env="DATABASE_USER=mizzou_user" \
    --env="DATABASE_PASSWORD=dummy" \
    --env="DATABASE_NAME=mizzou_prod" \
    -- python -m src.cli.main --help 2>&1 || true)

if echo "$OUTPUT" | grep -q "Falling back to SQLite"; then
    echo "❌ FAIL: SQLite warning still present"
    echo "   Output: $OUTPUT"
else
    echo "✅ PASS: No SQLite fallback warning"
fi

echo ""
echo "🎉 Test suite complete!"
