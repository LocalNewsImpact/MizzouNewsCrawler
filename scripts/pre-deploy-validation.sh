#!/bin/bash
set -euo pipefail

#######################################################################
# Pre-Deployment Validation Script
#
# This script runs all critical tests that would catch deployment issues
# BEFORE triggering any Cloud Build or deployment.
#
# Usage:
#   ./scripts/pre-deploy-validation.sh [service]
#
# Examples:
#   ./scripts/pre-deploy-validation.sh processor
#   ./scripts/pre-deploy-validation.sh api
#######################################################################

SERVICE="${1:-all}"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=========================================="
echo "Pre-Deployment Validation for: ${SERVICE}"
echo "=========================================="
echo ""

cd "$PROJECT_ROOT"

# Ensure virtual environment is activated
if [ -z "${VIRTUAL_ENV:-}" ]; then
    echo "⚠️  Virtual environment not active, activating..."
    if [ -d "venv/bin/activate" ]; then
        source venv/bin/activate
    else
        echo "❌ No virtual environment found at venv/"
        exit 1
    fi
fi

echo "✓ Virtual environment active: ${VIRTUAL_ENV}"
echo ""

#######################################################################
# 1. Unit Tests for Origin Proxy
#######################################################################
echo "=========================================="
echo "1. Running Origin Proxy Unit Tests"
echo "=========================================="

if [ "$SERVICE" = "processor" ] || [ "$SERVICE" = "all" ]; then
    pytest tests/test_origin_proxy.py -v || {
        echo "❌ Origin proxy unit tests FAILED"
        exit 1
    }
    echo "✓ Origin proxy unit tests passed"
    echo ""
fi

#######################################################################
# 2. Sitecustomize Integration Tests
#######################################################################
echo "=========================================="
echo "2. Running Sitecustomize Integration Tests"
echo "=========================================="

if [ "$SERVICE" = "processor" ] || [ "$SERVICE" = "all" ]; then
    # Install pyyaml if needed for these tests
    pip install -q pyyaml
    
    pytest tests/test_sitecustomize_integration.py -v || {
        echo "❌ Sitecustomize integration tests FAILED"
        echo ""
        echo "These tests validate:"
        echo "  - sitecustomize.py can load without breaking app imports"
        echo "  - PYTHONPATH configuration preserves /app path"
        echo "  - Metadata bypass works with PreparedRequest objects"
        echo ""
        exit 1
    }
    echo "✓ Sitecustomize integration tests passed"
    echo ""
fi

#######################################################################
# 3. Deployment YAML Validation
#######################################################################
echo "=========================================="
echo "3. Validating Deployment Configuration"
echo "=========================================="

if [ "$SERVICE" = "processor" ] || [ "$SERVICE" = "all" ]; then
    echo "Checking processor-deployment.yaml..."
    
    # Check PYTHONPATH includes /app
    if ! grep -q 'value: "/app:' k8s/processor-deployment.yaml; then
        echo "❌ PYTHONPATH does not include /app!"
        echo "   This will cause ModuleNotFoundError for src imports"
        echo ""
        echo "   Current PYTHONPATH:"
        grep -A1 "name: PYTHONPATH" k8s/processor-deployment.yaml || echo "   Not found!"
        echo ""
        echo "   Expected: value: \"/app:/opt/origin-shim\""
        exit 1
    fi
    
    # Check image is a placeholder (not :latest)
    if grep -q 'image:.*:latest' k8s/processor-deployment.yaml; then
        echo "❌ Deployment uses image:latest!"
        echo "   This prevents Cloud Deploy from updating pods"
        echo "   Use placeholder like 'image: processor' instead"
        exit 1
    fi
    
    # Check CPU limits are reasonable
    if grep -q 'cpu:.*[0-9]\+m' k8s/processor-deployment.yaml; then
        cpu_request=$(grep -A1 "requests:" k8s/processor-deployment.yaml | grep "cpu:" | awk '{print $2}' | tr -d '"')
        cpu_limit=$(grep -A1 "limits:" k8s/processor-deployment.yaml | grep "cpu:" | awk '{print $2}' | tr -d '"')
        
        echo "  CPU request: ${cpu_request}"
        echo "  CPU limit: ${cpu_limit}"
    fi
    
    echo "✓ Deployment YAML validation passed"
    echo ""
fi

#######################################################################
# 4. Skaffold Configuration Validation
#######################################################################
echo "=========================================="
echo "4. Validating Skaffold Configuration"
echo "=========================================="

if [ -f "skaffold.yaml" ]; then
    # Check that processor artifact is defined
    if ! grep -q 'image: processor' skaffold.yaml; then
        echo "❌ Skaffold config missing processor artifact!"
        exit 1
    fi
    
    # Check that manifests are defined
    if ! grep -q 'rawYaml:' skaffold.yaml; then
        echo "❌ Skaffold config missing manifest paths!"
        exit 1
    fi
    
    echo "✓ Skaffold configuration valid"
    echo ""
else
    echo "⚠️  No skaffold.yaml found (may be optional)"
    echo ""
fi

#######################################################################
# 5. Cloud Build Configuration Validation
#######################################################################
echo "=========================================="
echo "5. Validating Cloud Build Configuration"
echo "=========================================="

if [ "$SERVICE" = "processor" ] || [ "$SERVICE" = "all" ]; then
    if [ ! -f "cloudbuild-processor.yaml" ]; then
        echo "❌ cloudbuild-processor.yaml not found!"
        exit 1
    fi
    
    # Check that it uses Skaffold rendering
    if ! grep -q '\-\-skaffold\-file' cloudbuild-processor.yaml; then
        echo "❌ Cloud Build config doesn't use Skaffold rendering!"
        echo "   Add --skaffold-file=skaffold.yaml to release creation"
        exit 1
    fi
    
    echo "✓ Cloud Build configuration valid"
    echo ""
fi

#######################################################################
# 6. Git Status Check
#######################################################################
echo "=========================================="
echo "6. Checking Git Status"
echo "=========================================="

if [ -n "$(git status --porcelain)" ]; then
    echo "⚠️  Uncommitted changes detected:"
    git status --short
    echo ""
    echo "❌ Commit and push all changes before deploying!"
    echo ""
    echo "Run:"
    echo "  git add ."
    echo "  git commit -m 'Your commit message'"
    echo "  git push origin $(git branch --show-current)"
    echo ""
    exit 1
fi

echo "✓ All changes committed"
echo ""

# Check if current branch is pushed
if ! git diff --quiet origin/$(git branch --show-current) 2>/dev/null; then
    echo "⚠️  Local branch ahead of origin"
    echo "❌ Push changes before deploying!"
    echo ""
    echo "Run:"
    echo "  git push origin $(git branch --show-current)"
    echo ""
    exit 1
fi

echo "✓ Branch up to date with origin"
echo ""

#######################################################################
# Summary
#######################################################################
echo "=========================================="
echo "✅ PRE-DEPLOYMENT VALIDATION PASSED"
echo "=========================================="
echo ""
echo "All checks passed! Safe to deploy ${SERVICE}."
echo ""
echo "To deploy, run:"
echo "  gcloud builds triggers run build-${SERVICE}-manual --branch=$(git branch --show-current)"
echo ""
