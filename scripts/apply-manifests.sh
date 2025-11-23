#!/bin/bash
set -e

# Usage: ./scripts/apply-manifests.sh [file_path]
# If file_path is provided, applies only that file.
# If no argument, applies all manifests using the versions defined in k8s/versions.env.

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
    envsubst '${PROCESSOR_TAG} ${CRAWLER_TAG} ${API_TAG}' < "$file" | kubectl apply -f -
}

if [ -n "$1" ]; then
    apply_file "$1"
else
    echo "Applying all manifests..."
    # Add files here as they are converted to use variables
    apply_file k8s/housekeeping-cronjob.yaml
    apply_file k8s/processor-deployment.yaml
    # apply_file k8s/crawler-cronjob.yaml
fi
