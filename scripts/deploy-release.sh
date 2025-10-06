#!/bin/bash
# Deploy a coordinated release with specific image tags for all services
# Usage: ./scripts/deploy-release.sh <api-tag> <processor-tag> <crawler-tag>
# Example: ./scripts/deploy-release.sh 732b5d0 732b5d0 latest

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Configuration
PROJECT_ID="mizzou-news-crawler"
REGION="us-central1"
PIPELINE="mizzou-news-crawler"
REGISTRY="us-central1-docker.pkg.dev/${PROJECT_ID}/mizzou-crawler"

# Parse arguments
if [ $# -ne 3 ]; then
    log_error "Usage: $0 <api-tag> <processor-tag> <crawler-tag>"
    log_info "Example: $0 732b5d0 732b5d0 latest"
    exit 1
fi

API_TAG="$1"
PROCESSOR_TAG="$2"
CRAWLER_TAG="$3"
RELEASE_NAME="release-$(date +%Y%m%d-%H%M%S)"

log_info "Creating Cloud Deploy release:"
log_info "  Release: ${RELEASE_NAME}"
log_info "  API: ${API_TAG}"
log_info "  Processor: ${PROCESSOR_TAG}"
log_info "  Crawler: ${CRAWLER_TAG}"

# Verify images exist
log_info "Verifying images exist..."
for IMAGE in "api:${API_TAG}" "processor:${PROCESSOR_TAG}" "crawler:${CRAWLER_TAG}"; do
    if gcloud artifacts docker images describe "${REGISTRY}/${IMAGE}" --quiet >/dev/null 2>&1; then
        log_success "✓ ${IMAGE}"
    else
        log_error "✗ ${IMAGE} not found in registry"
        exit 1
    fi
done

# Create Cloud Deploy release
log_info "Creating Cloud Deploy release..."
gcloud deploy releases create "${RELEASE_NAME}" \
    --delivery-pipeline="${PIPELINE}" \
    --region="${REGION}" \
    --annotations="api=${API_TAG},processor=${PROCESSOR_TAG},crawler=${CRAWLER_TAG}" \
    --images="api=${REGISTRY}/api:${API_TAG},processor=${REGISTRY}/processor:${PROCESSOR_TAG},crawler=${REGISTRY}/crawler:${CRAWLER_TAG}"

log_success "Release created: ${RELEASE_NAME}"
log_info "Deployment will start automatically to the production target"
log_info ""
log_info "Monitor progress:"
log_info "  gcloud deploy rollouts list --release=${RELEASE_NAME} --delivery-pipeline=${PIPELINE} --region=${REGION}"
log_info ""
log_info "View in console:"
log_info "  https://console.cloud.google.com/deploy/delivery-pipelines/${REGION}/${PIPELINE}?project=${PROJECT_ID}"
