#!/bin/bash
# Quick test: See live telemetry data from production API

set -e

echo "🔍 Finding production API pod..."
API_POD=$(kubectl get pods -n production -l app=mizzou-api -o jsonpath='{.items[0].metadata.name}')

if [ -z "$API_POD" ]; then
    echo "❌ No API pod found"
    exit 1
fi

echo "✅ Found: $API_POD"
echo ""
echo "🚀 Starting port-forward to localhost:8000"
echo "   Press Ctrl+C to stop"
echo ""
echo "In another terminal, try:"
echo "  curl http://localhost:8000/api/telemetry/queue | jq"
echo "  curl http://localhost:8000/api/telemetry/summary | jq"
echo ""

kubectl port-forward -n production "$API_POD" 8000:8000
