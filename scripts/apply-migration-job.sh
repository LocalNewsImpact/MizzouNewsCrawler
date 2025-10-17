#!/bin/bash
# Helper script to apply migration job with correct image tag
# This script substitutes <COMMIT_SHA> placeholder with actual commit SHA

set -euo pipefail

# Usage information
usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Applies migration job to Kubernetes with correct image tag.

Options:
    -s, --sha COMMIT_SHA           Commit SHA to use for image tag (required)
    -n, --namespace NAMESPACE       Kubernetes namespace (default: default)
    -j, --job-type TYPE            Job type: basic or smoke-test (default: basic)
    -c, --context CONTEXT          Kubernetes context (optional)
    -d, --dry-run                  Show generated manifest without applying
    -h, --help                     Show this help message

Examples:
    # Apply basic migration job to default namespace
    $0 -s abc123def

    # Apply migration with smoke test to production
    $0 -s abc123def -n production -j smoke-test

    # Dry run to see generated manifest
    $0 -s abc123def --dry-run

    # Use specific kubectl context
    $0 -s abc123def -c my-cluster-context

EOF
    exit 1
}

# Default values
NAMESPACE="default"
JOB_TYPE="basic"
CONTEXT=""
DRY_RUN=false
COMMIT_SHA=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -s|--sha)
            COMMIT_SHA="$2"
            shift 2
            ;;
        -n|--namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        -j|--job-type)
            JOB_TYPE="$2"
            shift 2
            ;;
        -c|--context)
            CONTEXT="$2"
            shift 2
            ;;
        -d|--dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

# Validate required parameters
if [ -z "$COMMIT_SHA" ]; then
    echo "ERROR: Commit SHA is required"
    echo ""
    usage
fi

# Validate job type
if [ "$JOB_TYPE" != "basic" ] && [ "$JOB_TYPE" != "smoke-test" ]; then
    echo "ERROR: Job type must be 'basic' or 'smoke-test'"
    exit 1
fi

# Determine source manifest
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ "$JOB_TYPE" = "basic" ]; then
    SOURCE_MANIFEST="$PROJECT_ROOT/k8s/jobs/run-alembic-migrations.yaml"
else
    SOURCE_MANIFEST="$PROJECT_ROOT/k8s/jobs/run-alembic-migrations-with-smoke-test.yaml"
fi

# Verify source manifest exists
if [ ! -f "$SOURCE_MANIFEST" ]; then
    echo "ERROR: Source manifest not found: $SOURCE_MANIFEST"
    exit 1
fi

# Build kubectl command
KUBECTL_CMD="kubectl"
if [ -n "$CONTEXT" ]; then
    KUBECTL_CMD="$KUBECTL_CMD --context=$CONTEXT"
fi
KUBECTL_CMD="$KUBECTL_CMD --namespace=$NAMESPACE"

echo "========================================="
echo "Applying Migration Job"
echo "========================================="
echo "Job Type: $JOB_TYPE"
echo "Namespace: $NAMESPACE"
if [ -n "$CONTEXT" ]; then
    echo "Context: $CONTEXT"
fi
echo "Commit SHA: $COMMIT_SHA"
echo "Source: $SOURCE_MANIFEST"
echo ""

# Create temporary manifest with substituted SHA
TEMP_MANIFEST=$(mktemp)
trap "rm -f $TEMP_MANIFEST" EXIT

# Substitute <COMMIT_SHA> with actual commit SHA
sed "s/<COMMIT_SHA>/$COMMIT_SHA/g" "$SOURCE_MANIFEST" > "$TEMP_MANIFEST"

# Also update the job name to make it unique
TIMESTAMP=$(date +%s)
JOB_NAME="alembic-migration-${TIMESTAMP}"
sed -i "s/name: run-alembic-migrations/name: $JOB_NAME/g" "$TEMP_MANIFEST"
if [ "$JOB_TYPE" = "smoke-test" ]; then
    sed -i "s/name: run-alembic-migrations-with-smoke-test/name: $JOB_NAME/g" "$TEMP_MANIFEST"
fi

# Update namespace in manifest
sed -i "s/namespace: default/namespace: $NAMESPACE/g" "$TEMP_MANIFEST"

# Show the generated manifest
echo "Generated manifest:"
echo "---"
cat "$TEMP_MANIFEST"
echo "---"
echo ""

# Apply or dry-run
if [ "$DRY_RUN" = true ]; then
    echo "Dry run mode - manifest generated above (not applied)"
    exit 0
fi

# Verify migrator image exists
IMAGE="us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/migrator:$COMMIT_SHA"
echo "Checking if image exists: $IMAGE"
if command -v gcloud &> /dev/null; then
    if ! gcloud artifacts docker images describe "$IMAGE" >/dev/null 2>&1; then
        echo "WARNING: Could not verify image exists: $IMAGE"
        echo "Proceeding anyway..."
    else
        echo "✓ Image verified"
    fi
else
    echo "gcloud not available, skipping image verification"
fi
echo ""

# Apply the manifest
echo "Applying manifest..."
$KUBECTL_CMD apply -f "$TEMP_MANIFEST"

echo ""
echo "========================================="
echo "✓ Migration job applied successfully!"
echo "========================================="
echo ""
echo "Job name: $JOB_NAME"
echo ""
echo "Monitor with:"
echo "  $KUBECTL_CMD get job/$JOB_NAME -w"
echo ""
echo "View logs:"
echo "  $KUBECTL_CMD logs -l job-name=$JOB_NAME -f"
echo ""
echo "Check status:"
echo "  $KUBECTL_CMD describe job/$JOB_NAME"
echo ""
