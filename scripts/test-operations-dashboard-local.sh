#!/bin/bash
# Test Operations Dashboard locally with live production data
# This script:
# 1. Port-forwards the production API pod
# 2. Proxies frontend requests to production API
# 3. Keeps your local frontend running on :5173

set -e

echo "🔍 Finding production API pod..."
API_POD=$(kubectl get pods -n production -l app=mizzou-api -o jsonpath='{.items[0].metadata.name}')

if [ -z "$API_POD" ]; then
    echo "❌ No API pod found in production namespace"
    exit 1
fi

echo "✅ Found API pod: $API_POD"
echo ""
echo "🚀 Port-forwarding production API to localhost:8000"
echo "   Frontend on http://localhost:5173 will proxy to this"
echo ""
echo "⚠️  This gives you READ access to live production data"
echo "   Any POST/PUT/DELETE operations will affect production!"
echo ""
echo "Press Ctrl+C to stop port-forwarding"
echo ""

# Port-forward production API to local 8000
kubectl port-forward -n production "$API_POD" 8000:8000
