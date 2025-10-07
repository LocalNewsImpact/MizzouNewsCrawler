#!/bin/bash
# Validation script for proxy deployment in Kubernetes
# Usage: ./scripts/validate_proxy_deployment.sh [namespace] [deployment-name]

set -e

NAMESPACE=${1:-production}
DEPLOYMENT=${2:-mizzou-processor}

echo "==================================="
echo "Proxy Deployment Validation Script"
echo "==================================="
echo "Namespace: $NAMESPACE"
echo "Deployment: $DEPLOYMENT"
echo ""

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo "❌ ERROR: kubectl not found. Please install kubectl."
    exit 1
fi

echo "✓ kubectl found"

# Check if we can access the cluster
if ! kubectl cluster-info &> /dev/null; then
    echo "❌ ERROR: Cannot connect to Kubernetes cluster"
    exit 1
fi

echo "✓ Connected to cluster"

# Check if namespace exists
if ! kubectl get namespace "$NAMESPACE" &> /dev/null; then
    echo "❌ ERROR: Namespace $NAMESPACE not found"
    exit 1
fi

echo "✓ Namespace $NAMESPACE exists"

# Check if ConfigMap exists
echo ""
echo "--- Checking ConfigMap ---"
if kubectl get configmap origin-sitecustomize -n "$NAMESPACE" &> /dev/null; then
    echo "✓ ConfigMap 'origin-sitecustomize' exists"
    
    # Verify it contains sitecustomize.py
    if kubectl get configmap origin-sitecustomize -n "$NAMESPACE" -o yaml | grep -q "sitecustomize.py"; then
        echo "✓ ConfigMap contains sitecustomize.py"
    else
        echo "⚠ WARNING: ConfigMap does not contain sitecustomize.py"
    fi
else
    echo "⚠ WARNING: ConfigMap 'origin-sitecustomize' not found"
    echo "   Run: kubectl apply -f k8s/origin-sitecustomize-configmap.yaml"
fi

# Check if Secret exists
echo ""
echo "--- Checking Secret ---"
if kubectl get secret origin-proxy-credentials -n "$NAMESPACE" &> /dev/null; then
    echo "✓ Secret 'origin-proxy-credentials' exists"
    
    # Check if it has the required keys
    SECRET_KEYS=$(kubectl get secret origin-proxy-credentials -n "$NAMESPACE" -o jsonpath='{.data}' | grep -o '"[^"]*":' | tr -d '":' || echo "")
    
    for key in PROXY_USERNAME PROXY_PASSWORD ORIGIN_PROXY_URL SELENIUM_PROXY; do
        if echo "$SECRET_KEYS" | grep -q "$key"; then
            echo "  ✓ Secret has key: $key"
        else
            echo "  ⚠ WARNING: Secret missing key: $key"
        fi
    done
else
    echo "⚠ WARNING: Secret 'origin-proxy-credentials' not found"
    echo "   Create it with: kubectl create secret generic origin-proxy-credentials ..."
fi

# Check if deployment exists
echo ""
echo "--- Checking Deployment ---"
if ! kubectl get deployment "$DEPLOYMENT" -n "$NAMESPACE" &> /dev/null; then
    echo "❌ ERROR: Deployment $DEPLOYMENT not found in namespace $NAMESPACE"
    exit 1
fi

echo "✓ Deployment '$DEPLOYMENT' exists"

# Check if deployment has the volume mount
DEPLOYMENT_YAML=$(kubectl get deployment "$DEPLOYMENT" -n "$NAMESPACE" -o yaml)

if echo "$DEPLOYMENT_YAML" | grep -q "origin-sitecustomize"; then
    echo "✓ Deployment has origin-sitecustomize volume"
else
    echo "⚠ WARNING: Deployment does not have origin-sitecustomize volume"
    echo "   Update with: kubectl apply -f k8s/processor-deployment.yaml"
fi

# Check if deployment has USE_ORIGIN_PROXY env var
if echo "$DEPLOYMENT_YAML" | grep -q "USE_ORIGIN_PROXY"; then
    echo "✓ Deployment has USE_ORIGIN_PROXY environment variable"
    
    # Check the value
    USE_PROXY=$(echo "$DEPLOYMENT_YAML" | grep -A 1 "USE_ORIGIN_PROXY" | grep "value:" | awk '{print $2}' || echo "")
    if [ "$USE_PROXY" = "true" ] || [ "$USE_PROXY" = '"true"' ]; then
        echo "  ✓ USE_ORIGIN_PROXY is set to: true"
    else
        echo "  ⚠ USE_ORIGIN_PROXY is set to: $USE_PROXY (not 'true')"
    fi
else
    echo "⚠ WARNING: Deployment does not have USE_ORIGIN_PROXY environment variable"
fi

# Check if there's a running pod
echo ""
echo "--- Checking Pods ---"
POD=$(kubectl get pods -n "$NAMESPACE" -l app="$DEPLOYMENT" --field-selector=status.phase=Running -o name | head -n1 | sed 's#pod/##')

if [ -z "$POD" ]; then
    echo "⚠ WARNING: No running pods found for deployment $DEPLOYMENT"
    echo "   Check pod status with: kubectl get pods -n $NAMESPACE -l app=$DEPLOYMENT"
else
    echo "✓ Found running pod: $POD"
    
    # Check if sitecustomize.py is mounted
    echo ""
    echo "--- Checking Pod Configuration ---"
    if kubectl exec -n "$NAMESPACE" "$POD" -- test -f /usr/local/lib/python3.12/site-packages/sitecustomize.py 2>/dev/null; then
        echo "✓ sitecustomize.py is mounted in pod"
        
        # Check if it contains the expected content
        if kubectl exec -n "$NAMESPACE" "$POD" -- grep -q "origin-shim" /usr/local/lib/python3.12/site-packages/sitecustomize.py 2>/dev/null; then
            echo "✓ sitecustomize.py contains origin-shim code"
        fi
    else
        echo "⚠ WARNING: sitecustomize.py not found in pod"
        echo "   Expected at: /usr/local/lib/python3.12/site-packages/sitecustomize.py"
        
        # Try to find the correct path
        echo "   Checking actual site-packages path..."
        SITE_PACKAGES=$(kubectl exec -n "$NAMESPACE" "$POD" -- python -c "import site; print(site.getsitepackages()[0])" 2>/dev/null || echo "")
        if [ -n "$SITE_PACKAGES" ]; then
            echo "   Actual site-packages path: $SITE_PACKAGES"
            echo "   Update the mountPath in the deployment YAML to: $SITE_PACKAGES/sitecustomize.py"
        fi
    fi
    
    # Check environment variables in pod
    echo ""
    echo "--- Checking Environment Variables in Pod ---"
    ENV_VARS=$(kubectl exec -n "$NAMESPACE" "$POD" -- printenv 2>/dev/null || echo "")
    
    for var in USE_ORIGIN_PROXY ORIGIN_PROXY_URL PROXY_USERNAME PROXY_PASSWORD SELENIUM_PROXY; do
        if echo "$ENV_VARS" | grep -q "^${var}="; then
            VALUE=$(echo "$ENV_VARS" | grep "^${var}=" | cut -d'=' -f2- | head -c 50)
            if [ "$var" = "PROXY_PASSWORD" ]; then
                echo "  ✓ $var=***"
            else
                echo "  ✓ $var=$VALUE"
            fi
        else
            echo "  ⚠ $var not set"
        fi
    done
    
    # Test if Python can load sitecustomize
    echo ""
    echo "--- Testing Python Import ---"
    if kubectl exec -n "$NAMESPACE" "$POD" -- python -c "import importlib.util; spec = importlib.util.spec_from_file_location('sitecustomize', '/usr/local/lib/python3.12/site-packages/sitecustomize.py'); sitecustomize = importlib.util.module_from_spec(spec); spec.loader.exec_module(sitecustomize); print('✓ sitecustomize loaded successfully')" 2>/dev/null; then
        echo "✓ sitecustomize can be imported successfully"
    else
        echo "⚠ WARNING: Could not import sitecustomize"
    fi
    
    # Test a simple HTTP request
    echo ""
    echo "--- Testing HTTP Request ---"
    echo "Attempting to make a test request..."
    if kubectl exec -n "$NAMESPACE" "$POD" -- python -c "import requests; r = requests.get('http://example.com', timeout=10); print(f'✓ Request succeeded with status {r.status_code}')" 2>/dev/null; then
        echo "✓ Test request successful"
    else
        echo "⚠ Test request failed (this may be expected if proxy requires valid credentials)"
    fi
fi

echo ""
echo "==================================="
echo "Validation Complete"
echo "==================================="
echo ""
echo "Next steps:"
echo "1. If ConfigMap is missing, apply it: kubectl apply -f k8s/origin-sitecustomize-configmap.yaml"
echo "2. If Secret is missing, create it with actual credentials"
echo "3. If deployment needs updates, apply: kubectl apply -f k8s/processor-deployment.yaml"
echo "4. Restart deployment: kubectl rollout restart deployment/$DEPLOYMENT -n $NAMESPACE"
echo "5. Check logs: kubectl logs -n $NAMESPACE $POD | grep origin-shim"
echo ""
