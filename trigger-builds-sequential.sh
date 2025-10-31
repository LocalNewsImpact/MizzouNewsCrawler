#!/bin/bash

# Sequential build trigger with completion monitoring
# Ensures each build completes before starting dependent builds

set -e

PROJECT="mizzou-news-crawler"
BRANCH="main"

echo "Starting sequential build process with completion monitoring..."
echo "================================================================"

# Function to wait for a build to complete
wait_for_build() {
    local build_id=$1
    local build_name=$2
    
    echo ""
    echo "Waiting for $build_name (ID: $build_id) to complete..."
    
    while true; do
        status=$(gcloud builds describe "$build_id" --project="$PROJECT" --format="value(status)" 2>/dev/null || echo "UNKNOWN")
        
        case "$status" in
            "SUCCESS")
                echo "✓ $build_name completed successfully!"
                return 0
                ;;
            "FAILURE"|"CANCELLED"|"TIMEOUT"|"INTERNAL_ERROR")
                echo "✗ $build_name failed with status: $status"
                return 1
                ;;
            "WORKING"|"QUEUED")
                echo -n "."
                sleep 30
                ;;
            *)
                echo "? Unknown status: $status"
                sleep 30
                ;;
        esac
    done
}

# Build 1: Base Image
echo ""
echo "Step 1/5: Triggering base image build..."
BASE_OUTPUT=$(gcloud builds triggers run build-base-manual --branch="$BRANCH" --project="$PROJECT" --format="value(metadata.build.id)")
BASE_BUILD_ID=$(echo "$BASE_OUTPUT" | tail -1)
echo "Base build started (ID: $BASE_BUILD_ID)"
wait_for_build "$BASE_BUILD_ID" "Base Image" || exit 1

# Build 2: CI Base Image (depends on base)
echo ""
echo "Step 2/5: Triggering CI base image build..."
CI_BASE_OUTPUT=$(gcloud builds triggers run build-ci-base-manual --branch="$BRANCH" --project="$PROJECT" --format="value(metadata.build.id)")
CI_BASE_BUILD_ID=$(echo "$CI_BASE_OUTPUT" | tail -1)
echo "CI base build started (ID: $CI_BASE_BUILD_ID)"
wait_for_build "$CI_BASE_BUILD_ID" "CI Base Image" || exit 1

# Build 3: ML Base Image (depends on base)
echo ""
echo "Step 3/5: Triggering ML base image build..."
ML_BASE_OUTPUT=$(gcloud builds triggers run build-ml-base-manual --branch="$BRANCH" --project="$PROJECT" --format="value(metadata.build.id)")
ML_BASE_BUILD_ID=$(echo "$ML_BASE_OUTPUT" | tail -1)
echo "ML base build started (ID: $ML_BASE_BUILD_ID)"
wait_for_build "$ML_BASE_BUILD_ID" "ML Base Image" || exit 1

# Build 4: Service Images (depend on ml-base) - can run in parallel
echo ""
echo "Step 4/5: Triggering service image builds (API, Crawler, Processor)..."

API_OUTPUT=$(gcloud builds triggers run build-api-manual --branch="$BRANCH" --project="$PROJECT" --format="value(metadata.build.id)")
API_BUILD_ID=$(echo "$API_OUTPUT" | tail -1)
echo "API build started (ID: $API_BUILD_ID)"

sleep 10

CRAWLER_OUTPUT=$(gcloud builds triggers run build-crawler-manual --branch="$BRANCH" --project="$PROJECT" --format="value(metadata.build.id)")
CRAWLER_BUILD_ID=$(echo "$CRAWLER_OUTPUT" | tail -1)
echo "Crawler build started (ID: $CRAWLER_BUILD_ID)"

sleep 10

PROCESSOR_OUTPUT=$(gcloud builds triggers run build-processor-manual --branch="$BRANCH" --project="$PROJECT" --format="value(metadata.build.id)")
PROCESSOR_BUILD_ID=$(echo "$PROCESSOR_OUTPUT" | tail -1)
echo "Processor build started (ID: $PROCESSOR_BUILD_ID)"

# Wait for all service builds
echo ""
echo "Step 5/5: Waiting for all service builds to complete..."
wait_for_build "$API_BUILD_ID" "API Service" &
API_PID=$!
wait_for_build "$CRAWLER_BUILD_ID" "Crawler Service" &
CRAWLER_PID=$!
wait_for_build "$PROCESSOR_BUILD_ID" "Processor Service" &
PROCESSOR_PID=$!

# Wait for all background processes
wait $API_PID
API_RESULT=$?
wait $CRAWLER_PID
CRAWLER_RESULT=$?
wait $PROCESSOR_PID
PROCESSOR_RESULT=$?

echo ""
echo "================================================================"
echo "Build Summary:"
echo "  Base:      $BASE_BUILD_ID - SUCCESS"
echo "  CI Base:   $CI_BASE_BUILD_ID - SUCCESS"
echo "  ML Base:   $ML_BASE_BUILD_ID - SUCCESS"
echo "  API:       $API_BUILD_ID - $([ $API_RESULT -eq 0 ] && echo 'SUCCESS' || echo 'FAILED')"
echo "  Crawler:   $CRAWLER_BUILD_ID - $([ $CRAWLER_RESULT -eq 0 ] && echo 'SUCCESS' || echo 'FAILED')"
echo "  Processor: $PROCESSOR_BUILD_ID - $([ $PROCESSOR_RESULT -eq 0 ] && echo 'SUCCESS' || echo 'FAILED')"
echo "================================================================"

# Exit with error if any service build failed
if [ $API_RESULT -ne 0 ] || [ $CRAWLER_RESULT -ne 0 ] || [ $PROCESSOR_RESULT -ne 0 ]; then
    echo "One or more service builds failed!"
    exit 1
fi

echo ""
echo "All builds completed successfully! 🎉"
