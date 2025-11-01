#!/bin/bash
set -e

# Deploy All Services Script
# Rebuilds base → ml-base → api/crawler/processor with proper wait times

BRANCH="${1:-main}"
COLOR_GREEN='\033[0;32m'
COLOR_BLUE='\033[0;34m'
COLOR_YELLOW='\033[1;33m'
COLOR_RED='\033[0;31m'
COLOR_RESET='\033[0m'

echo -e "${COLOR_BLUE}========================================${COLOR_RESET}"
echo -e "${COLOR_BLUE}Deploying All Services from branch: ${BRANCH}${COLOR_RESET}"
echo -e "${COLOR_BLUE}========================================${COLOR_RESET}"

# Function to wait for Cloud Build to complete
wait_for_build() {
    local build_id=$1
    local service_name=$2
    
    echo -e "${COLOR_YELLOW}⏳ Waiting for ${service_name} build to complete...${COLOR_RESET}"
    
    while true; do
        status=$(gcloud builds describe "$build_id" --format='value(status)')
        
        if [ "$status" = "SUCCESS" ]; then
            echo -e "${COLOR_GREEN}✅ ${service_name} build completed successfully${COLOR_RESET}"
            return 0
        elif [ "$status" = "FAILURE" ] || [ "$status" = "TIMEOUT" ] || [ "$status" = "CANCELLED" ]; then
            echo -e "${COLOR_RED}❌ ${service_name} build failed with status: ${status}${COLOR_RESET}"
            return 1
        fi
        
        echo -e "${COLOR_YELLOW}   Status: ${status}... (checking again in 30s)${COLOR_RESET}"
        sleep 30
    done
}

# Step 1: Build Base Image
echo -e "\n${COLOR_BLUE}Step 1/6: Building Base Image${COLOR_RESET}"
BASE_BUILD_ID=$(gcloud builds triggers run build-base-manual --branch="$BRANCH" --format='value(metadata.build.id)')
echo "Build ID: $BASE_BUILD_ID"
wait_for_build "$BASE_BUILD_ID" "Base Image"

# Step 2: Build ML Base Image
echo -e "\n${COLOR_BLUE}Step 2/6: Building ML Base Image${COLOR_RESET}"
ML_BASE_BUILD_ID=$(gcloud builds triggers run build-ml-base-manual --branch="$BRANCH" --format='value(metadata.build.id)')
echo "Build ID: $ML_BASE_BUILD_ID"
wait_for_build "$ML_BASE_BUILD_ID" "ML Base Image"

# Step 3: Build API
echo -e "\n${COLOR_BLUE}Step 3/6: Building API Service${COLOR_RESET}"
API_BUILD_ID=$(gcloud builds triggers run build-api-manual --branch="$BRANCH" --format='value(metadata.build.id)')
echo "Build ID: $API_BUILD_ID"
wait_for_build "$API_BUILD_ID" "API Service"

# Step 4: Build Crawler
echo -e "\n${COLOR_BLUE}Step 4/6: Building Crawler Service${COLOR_RESET}"
CRAWLER_BUILD_ID=$(gcloud builds triggers run build-crawler-manual --branch="$BRANCH" --format='value(metadata.build.id)')
echo "Build ID: $CRAWLER_BUILD_ID"
wait_for_build "$CRAWLER_BUILD_ID" "Crawler Service"

# Step 5: Build Processor
echo -e "\n${COLOR_BLUE}Step 5/6: Building Processor Service${COLOR_RESET}"
PROCESSOR_BUILD_ID=$(gcloud builds triggers run build-processor-manual --branch="$BRANCH" --format='value(metadata.build.id)')
echo "Build ID: $PROCESSOR_BUILD_ID"
wait_for_build "$PROCESSOR_BUILD_ID" "Processor Service"

# Step 6: Get the commit SHA for the deployed images
COMMIT_SHA=$(git rev-parse --short HEAD)

echo -e "\n${COLOR_GREEN}========================================${COLOR_RESET}"
echo -e "${COLOR_GREEN}✅ All Services Deployed Successfully!${COLOR_RESET}"
echo -e "${COLOR_GREEN}========================================${COLOR_RESET}"
echo -e "Commit SHA: ${COLOR_BLUE}${COMMIT_SHA}${COLOR_RESET}"
echo -e "\nDeployed images:"
echo -e "  • ${COLOR_BLUE}api:${COMMIT_SHA}${COLOR_RESET}"
echo -e "  • ${COLOR_BLUE}crawler:${COMMIT_SHA}${COLOR_RESET}"
echo -e "  • ${COLOR_BLUE}processor:${COMMIT_SHA}${COLOR_RESET}"

echo -e "\n${COLOR_YELLOW}Next Steps:${COLOR_RESET}"
echo -e "1. Wait for K8s to pull new images (~2-5 minutes)"
echo -e "2. Verify pods are running: ${COLOR_BLUE}kubectl get pods -n production${COLOR_RESET}"
echo -e "3. Run migration: ${COLOR_BLUE}./scripts/run-migration-production.sh${COLOR_RESET}"

echo -e "\n${COLOR_GREEN}Deployment complete!${COLOR_RESET}"
