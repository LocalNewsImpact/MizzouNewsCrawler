#!/bin/bash
set -e

# Usage: ./scripts/apply-manifests.sh [services...]
# Services: api, processor, crawler, all (or no args for all)
# Examples:
#   ./scripts/apply-manifests.sh crawler           # Only crawler manifests
#   ./scripts/apply-manifests.sh api processor     # API and processor manifests
#   ./scripts/apply-manifests.sh all               # All manifests (same as no args)
#   ./scripts/apply-manifests.sh                   # All manifests

# Source versions
source k8s/versions.env

apply_file() {
    local file=$1
    if [ ! -f "$file" ]; then
        echo "❌ File not found: $file"
        return 1
    fi

    echo "🚀 Applying $file with substitutions..."
    # Use envsubst to replace variables defined in versions.env
    # We only substitute variables that are defined to avoid breaking other $VARs in the yaml
    envsubst '${PROCESSOR_TAG} ${CRAWLER_TAG} ${API_TAG}' < "$file" | kubectl apply -n production -f -
}

apply_api() {
    apply_file k8s/api-deployment.yaml
}

apply_processor() {
    apply_file k8s/processor-deployment.yaml
}

apply_crawler() {
    apply_file k8s/work-queue-deployment.yaml
    apply_file k8s/crawler-cronjob.yaml
    apply_file k8s/housekeeping-cronjob.yaml
    # Apply Minnesota Argo workflow (runs on demand, not continuously)
    kubectl apply -n production -f k8s/argo/minnesota-processing-workflow.yaml
}

apply_all() {
    echo "Applying all manifests..."
    apply_api
    apply_processor
    apply_crawler
}

# Parse arguments
if [ $# -eq 0 ]; then
    apply_all
else
    for arg in "$@"; do
        case "$arg" in
            all)
                apply_all
                ;;
            api)
                apply_api
                ;;
            processor)
                apply_processor
                ;;
            crawler)
                apply_crawler
                ;;
            *)
                # Treat as file path for backwards compatibility
                if [ -f "$arg" ]; then
                    apply_file "$arg"
                else
                    echo "❌ Unknown service or file: $arg"
                    echo "Valid services: api, processor, crawler, all"
                    exit 1
                fi
                ;;
        esac
    done
fi
