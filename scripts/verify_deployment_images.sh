#!/bin/bash
# Script to verify that Cloud Deploy successfully updated image tags in production
# This should be run after a Cloud Deploy rollout to ensure pods are using the expected image tags

set -euo pipefail

NAMESPACE="${NAMESPACE:-production}"
EXPECTED_TAG="${1:-}"

echo "🔍 Verifying deployment images in namespace: ${NAMESPACE}"
echo ""

# Function to check deployment image
check_deployment_image() {
    local deployment_name=$1
    local container_name=$2
    
    echo "📦 Checking ${deployment_name}..."
    
    local current_image=$(kubectl get deployment "${deployment_name}" \
        -n "${NAMESPACE}" \
        -o jsonpath="{.spec.template.spec.containers[?(@.name=='${container_name}')].image}" \
        2>/dev/null || echo "DEPLOYMENT_NOT_FOUND")
    
    if [ "${current_image}" = "DEPLOYMENT_NOT_FOUND" ]; then
        echo "   ⚠️  Deployment not found: ${deployment_name}"
        return 1
    fi
    
    echo "   Current image: ${current_image}"
    
    # Extract just the tag from the image
    local current_tag=$(echo "${current_image}" | awk -F: '{print $NF}')
    echo "   Current tag: ${current_tag}"
    
    # If expected tag provided, verify it matches
    if [ -n "${EXPECTED_TAG}" ]; then
        if [ "${current_tag}" = "${EXPECTED_TAG}" ]; then
            echo "   ✅ Image tag matches expected: ${EXPECTED_TAG}"
        else
            echo "   ❌ Image tag mismatch! Expected: ${EXPECTED_TAG}, Got: ${current_tag}"
            return 1
        fi
    fi
    
    # Check if pods are running with this image
    echo "   🔄 Checking pod status..."
    local pod_count=$(kubectl get pods -n "${NAMESPACE}" \
        -l "app=${deployment_name}" \
        --field-selector=status.phase=Running \
        -o json | jq '.items | length')
    
    echo "   Running pods: ${pod_count}"
    
    if [ "${pod_count}" -eq 0 ]; then
        echo "   ⚠️  No running pods found for ${deployment_name}"
        return 1
    fi
    
    # Get actual image from running pod
    local pod_image=$(kubectl get pods -n "${NAMESPACE}" \
        -l "app=${deployment_name}" \
        --field-selector=status.phase=Running \
        -o jsonpath="{.items[0].spec.containers[?(@.name=='${container_name}')].image}" \
        2>/dev/null || echo "UNKNOWN")
    
    echo "   Pod image: ${pod_image}"
    
    if [ "${current_image}" = "${pod_image}" ]; then
        echo "   ✅ Pod image matches deployment spec"
    else
        echo "   ⚠️  Pod image differs from deployment spec (rollout may be in progress)"
    fi
    
    echo ""
    return 0
}

# Check all deployments
echo "Checking processor deployment..."
check_deployment_image "mizzou-processor" "processor" || true

echo "Checking API deployment..."
check_deployment_image "mizzou-api" "api" || true

echo "Checking CLI deployment..."
check_deployment_image "mizzou-cli" "cli" || true

echo ""
echo "🎯 Summary"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "To manually update images (if needed):"
echo "  kubectl set image deployment/mizzou-processor processor=IMAGE:TAG -n ${NAMESPACE}"
echo "  kubectl set image deployment/mizzou-api api=IMAGE:TAG -n ${NAMESPACE}"
echo ""
echo "To check Cloud Deploy releases:"
echo "  gcloud deploy releases list --delivery-pipeline=mizzou-news-crawler --region=us-central1"
echo ""
echo "To check rollout status:"
echo "  gcloud deploy rollouts list --delivery-pipeline=mizzou-news-crawler --region=us-central1 --release=RELEASE_NAME"
echo ""
