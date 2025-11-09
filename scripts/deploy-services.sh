#!/bin/bash
set -e

# Flexible Build Script for GCP Services
# Usage: ./scripts/deploy-services.sh [branch] [services...]
# Services: base, ml, api, crawler, processor, ci (or 'all')
# Examples:
#   ./scripts/deploy-services.sh fix/telemetrystring crawler processor
#   ./scripts/deploy-services.sh main base ml processor
#   ./scripts/deploy-services.sh main all
#   ./scripts/deploy-services.sh main ci  # Just CI/CD services (api, crawler, processor)

# Ensure gcloud CLI is available
if ! command -v gcloud >/dev/null 2>&1; then
    if [ -f "$HOME/google-cloud-sdk/path.bash.inc" ]; then
        # shellcheck disable=SC1090
        source "$HOME/google-cloud-sdk/path.bash.inc"
    fi
    if [ -f "$HOME/google-cloud-sdk/completion.bash.inc" ]; then
        # shellcheck disable=SC1090
        source "$HOME/google-cloud-sdk/completion.bash.inc"
    fi
fi

if ! command -v gcloud >/dev/null 2>&1 && [ -d "/opt/homebrew/bin" ]; then
    export PATH="/opt/homebrew/bin:$PATH"
fi

if ! command -v gcloud >/dev/null 2>&1; then
    echo "❌ gcloud CLI not found. Please install Google Cloud SDK." >&2
    exit 1
fi

# Colors
COLOR_GREEN='\033[0;32m'
COLOR_BLUE='\033[0;34m'
COLOR_YELLOW='\033[1;33m'
COLOR_RED='\033[0;31m'
COLOR_CYAN='\033[0;36m'
COLOR_RESET='\033[0m'

# Parse arguments -- prefer current git branch when available.
# If the user did not pass a branch explicitly and there are uncommitted
# changes in the working tree, abort to avoid accidentally triggering
# remote builds for the wrong code state.
if [ -n "${1:-}" ]; then
    BRANCH="$1"
    shift || true
else
    # If we're inside a git work tree, prefer the current branch name.
    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        # Abort if there are uncommitted changes to avoid accidental builds
        if [ -n "$(git status --porcelain)" ]; then
            echo -e "${COLOR_RED}❌ Uncommitted changes detected in the working tree.${COLOR_RESET}"
            echo -e "${COLOR_YELLOW}By default this script builds the current branch, but local uncommitted changes won't be included in remote builds.${COLOR_RESET}"
            echo -e "${COLOR_YELLOW}Commit or stash changes, or pass an explicit branch to continue:${COLOR_RESET} ./scripts/deploy-services.sh <branch> [services]"
            exit 1
        fi

        BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
    else
        # Not a git checkout (CI/CD environment) — fall back to main
        BRANCH="main"
    fi
fi

# Service selection
SERVICES_TO_BUILD=()
USE_MAIN_PIPELINE=false

if [ $# -eq 0 ]; then
    echo -e "${COLOR_YELLOW}⚠️  No services specified. Building all services.${COLOR_RESET}"
    SERVICES_TO_BUILD=("base" "ml" "api" "crawler" "processor")
    USE_MAIN_PIPELINE=true
else
    for arg in "$@"; do
        case "$arg" in
            all)
                SERVICES_TO_BUILD=("base" "ml" "api" "crawler" "processor")
                USE_MAIN_PIPELINE=true
                break
                ;;
            services)
                # Application services only (no base images) - use individual triggers
                SERVICES_TO_BUILD+=("api" "crawler" "processor")
                ;;
            ci)
                # Legacy alias for 'services'
                SERVICES_TO_BUILD+=("api" "crawler" "processor")
                ;;
            base|ml|api|crawler|processor)
                SERVICES_TO_BUILD+=("$arg")
                ;;
            *)
                echo -e "${COLOR_RED}❌ Unknown service: $arg${COLOR_RESET}"
                echo "Valid services: base, ml, api, crawler, processor, services, ci, all"
                exit 1
                ;;
        esac
    done
fi

# Remove duplicates and maintain order
SERVICES_TO_BUILD=($(echo "${SERVICES_TO_BUILD[@]}" | tr ' ' '\n' | awk '!seen[$0]++'))

# Use main cloudbuild.yaml pipeline for multi-service builds (includes migrations)
if [ "$USE_MAIN_PIPELINE" = true ]; then
    echo -e "${COLOR_BLUE}========================================${COLOR_RESET}"
    echo -e "${COLOR_BLUE}GCP Service Deployment (Main Pipeline)${COLOR_RESET}"
    echo -e "${COLOR_BLUE}========================================${COLOR_RESET}"
    echo -e "${COLOR_CYAN}Branch:${COLOR_RESET}    ${BRANCH}"
    echo -e "${COLOR_CYAN}Services:${COLOR_RESET}  ${SERVICES_TO_BUILD[*]}"
    echo -e "${COLOR_CYAN}Pipeline:${COLOR_RESET}  Build → Migrate → Deploy"
    echo -e "${COLOR_BLUE}========================================${COLOR_RESET}\n"
    
    gcloud builds submit --config=gcp/cloudbuild/cloudbuild.yaml \
        --project=mizzou-news-crawler \
        --substitutions=BRANCH_NAME="${BRANCH}"
    
    exit $?
fi

# Individual service builds (no migrations)
echo -e "${COLOR_BLUE}========================================${COLOR_RESET}"
echo -e "${COLOR_BLUE}GCP Service Deployment${COLOR_RESET}"
echo -e "${COLOR_BLUE}========================================${COLOR_RESET}"
echo -e "${COLOR_CYAN}Branch:${COLOR_RESET}    ${BRANCH}"
echo -e "${COLOR_CYAN}Services:${COLOR_RESET}  ${SERVICES_TO_BUILD[*]}"
echo -e "${COLOR_BLUE}========================================${COLOR_RESET}"

# Dependency graph:
# base → ml, api, crawler
# ml → processor
# No dependencies: (standalone builds)

# Function to check if service is in build list
should_build() {
    local service=$1
    for s in "${SERVICES_TO_BUILD[@]}"; do
        if [ "$s" = "$service" ]; then
            return 0
        fi
    done
    return 1
}

# Function to wait for Cloud Build to complete
wait_for_build() {
    local build_id=$1
    local service_name=$2
    
    echo -e "${COLOR_YELLOW}⏳ Waiting for ${service_name} build to complete...${COLOR_RESET}"
    
    # Get project ID
    local project_id
    project_id=$(gcloud config get-value project 2>/dev/null)
    
    while true; do
        if ! status=$(gcloud builds describe "$build_id" --project="$project_id" --format='value(status)' 2>&1); then
            echo -e "${COLOR_RED}❌ Error querying build status: ${status}${COLOR_RESET}"
            echo -e "${COLOR_YELLOW}View logs: gcloud builds log ${build_id} --project=${project_id}${COLOR_RESET}"
            return 1
        fi
        
        if [ "$status" = "SUCCESS" ]; then
            echo -e "${COLOR_GREEN}✅ ${service_name} build completed successfully${COLOR_RESET}"
            return 0
        elif [ "$status" = "FAILURE" ] || [ "$status" = "TIMEOUT" ] || [ "$status" = "CANCELLED" ]; then
            echo -e "${COLOR_RED}❌ ${service_name} build failed with status: ${status}${COLOR_RESET}"
            echo -e "${COLOR_YELLOW}View logs: gcloud builds log ${build_id} --project=${project_id}${COLOR_RESET}"
            return 1
        fi
        
        echo -e "${COLOR_YELLOW}   Status: ${status}... (checking again in 30s)${COLOR_RESET}"
        sleep 30
    done
}

# Function to trigger build
trigger_build() {
    local trigger_name=$1
    local service_name=$2
    local branch=$3
    
    echo -e "\n${COLOR_BLUE}🔨 Building: ${service_name}${COLOR_RESET}" >&2
    
    local build_id
    local build_output
    # Redirect stderr to /dev/null to avoid capturing extra output
    build_output=$(gcloud builds triggers run "$trigger_name" --branch="$branch" --format='value(metadata.build.id)' 2>/dev/null)
    local exit_code=$?
    
    if [ $exit_code -ne 0 ]; then
        echo -e "${COLOR_RED}❌ Failed to trigger ${service_name} build${COLOR_RESET}" >&2
        # Run again to show error
        gcloud builds triggers run "$trigger_name" --branch="$branch" >&2
        return 1
    fi
    
    # Extract just the build ID (first line, trimmed)
    build_id=$(echo "$build_output" | grep -E '^[a-f0-9-]+$' | head -n 1 | tr -d '[:space:]')
    
    echo -e "${COLOR_CYAN}Build ID:${COLOR_RESET} $build_id" >&2
    echo "$build_id"
}

# Track build status
BUILD_FAILURES=0
STEP_COUNTER=1
TOTAL_STEPS=${#SERVICES_TO_BUILD[@]}

# PHASE 1: Base Image (must complete before anything else)
if should_build "base"; then
    echo -e "\n${COLOR_BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${COLOR_RESET}"
    echo -e "${COLOR_BLUE}Phase 1: Base Image (Step ${STEP_COUNTER}/${TOTAL_STEPS})${COLOR_RESET}"
    echo -e "${COLOR_BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${COLOR_RESET}"
    BASE_BUILD_ID=$(trigger_build "build-base-manual" "Base Image" "$BRANCH")
    if ! wait_for_build "$BASE_BUILD_ID" "Base Image"; then
        ((BUILD_FAILURES++))
        echo -e "${COLOR_RED}❌ Base image failed. Dependent services (ml, api, crawler) cannot be built.${COLOR_RESET}"
        # Cannot continue if base fails and we need dependent services
        if should_build "ml" || should_build "api" || should_build "crawler"; then
            echo -e "${COLOR_RED}❌ Aborting build due to base image failure.${COLOR_RESET}"
            exit 1
        fi
    fi
    ((STEP_COUNTER++))
fi

# PHASE 2: ML Base Image (depends on base, needed by processor)
if should_build "ml"; then
    echo -e "\n${COLOR_BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${COLOR_RESET}"
    echo -e "${COLOR_BLUE}Phase 2: ML Base Image (Step ${STEP_COUNTER}/${TOTAL_STEPS})${COLOR_RESET}"
    echo -e "${COLOR_BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${COLOR_RESET}"
    
    # Check if base was built or already exists
    if ! should_build "base"; then
        echo -e "${COLOR_YELLOW}⚠️  Building ML base without rebuilding base image (using existing base)${COLOR_RESET}"
    fi
    
    ML_BASE_BUILD_ID=$(trigger_build "build-ml-base-manual" "ML Base Image" "$BRANCH")
    if ! wait_for_build "$ML_BASE_BUILD_ID" "ML Base Image"; then
        ((BUILD_FAILURES++))
        echo -e "${COLOR_RED}❌ ML base image failed. Processor cannot be built.${COLOR_RESET}"
        # Cannot continue if ml-base fails and we need processor
        if should_build "processor"; then
            echo -e "${COLOR_RED}❌ Aborting processor build due to ML base failure.${COLOR_RESET}"
            # Remove processor from build list
            SERVICES_TO_BUILD=("${SERVICES_TO_BUILD[@]/processor}")
        fi
    fi
    ((STEP_COUNTER++))
fi

# PHASE 3: Application Services (api, crawler can build in parallel)
# These depend on base but not on each other

PARALLEL_BUILDS=()
PARALLEL_SERVICES=()

if should_build "api"; then
    echo -e "\n${COLOR_BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${COLOR_RESET}"
    echo -e "${COLOR_BLUE}Phase 3a: API Service (Step ${STEP_COUNTER}/${TOTAL_STEPS})${COLOR_RESET}"
    echo -e "${COLOR_BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${COLOR_RESET}"
    
    if ! should_build "base"; then
        echo -e "${COLOR_YELLOW}⚠️  Building API without rebuilding base image (using existing base)${COLOR_RESET}"
    fi
    
    API_BUILD_ID=$(trigger_build "build-api-manual" "API Service" "$BRANCH")
    PARALLEL_BUILDS+=("$API_BUILD_ID")
    PARALLEL_SERVICES+=("API Service")
    ((STEP_COUNTER++))
fi

if should_build "crawler"; then
    echo -e "\n${COLOR_BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${COLOR_RESET}"
    echo -e "${COLOR_BLUE}Phase 3b: Crawler Service (Step ${STEP_COUNTER}/${TOTAL_STEPS})${COLOR_RESET}"
    echo -e "${COLOR_BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${COLOR_RESET}"
    
    if ! should_build "base"; then
        echo -e "${COLOR_YELLOW}⚠️  Building Crawler without rebuilding base image (using existing base)${COLOR_RESET}"
    fi
    
    CRAWLER_BUILD_ID=$(trigger_build "build-crawler-manual" "Crawler Service" "$BRANCH")
    PARALLEL_BUILDS+=("$CRAWLER_BUILD_ID")
    PARALLEL_SERVICES+=("Crawler Service")
    ((STEP_COUNTER++))
fi

# Wait for parallel builds (api, crawler)
if [ ${#PARALLEL_BUILDS[@]} -gt 0 ]; then
    echo -e "\n${COLOR_YELLOW}⏳ Waiting for ${#PARALLEL_BUILDS[@]} parallel builds to complete...${COLOR_RESET}"
    for i in "${!PARALLEL_BUILDS[@]}"; do
        if ! wait_for_build "${PARALLEL_BUILDS[$i]}" "${PARALLEL_SERVICES[$i]}"; then
            ((BUILD_FAILURES++))
        fi
    done
fi

# PHASE 4: Processor (depends on ml-base)
if should_build "processor"; then
    echo -e "\n${COLOR_BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${COLOR_RESET}"
    echo -e "${COLOR_BLUE}Phase 4: Processor Service (Step ${STEP_COUNTER}/${TOTAL_STEPS})${COLOR_RESET}"
    echo -e "${COLOR_BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${COLOR_RESET}"
    
    if ! should_build "ml"; then
        echo -e "${COLOR_YELLOW}⚠️  Building Processor without rebuilding ML base (using existing ml-base)${COLOR_RESET}"
    fi
    
    PROCESSOR_BUILD_ID=$(trigger_build "build-processor-manual" "Processor Service" "$BRANCH")
    if ! wait_for_build "$PROCESSOR_BUILD_ID" "Processor Service"; then
        ((BUILD_FAILURES++))
    fi
    ((STEP_COUNTER++))
fi

# Summary
COMMIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

echo -e "\n${COLOR_BLUE}========================================${COLOR_RESET}"
if [ $BUILD_FAILURES -eq 0 ]; then
    echo -e "${COLOR_GREEN}✅ All Builds Completed Successfully!${COLOR_RESET}"
else
    echo -e "${COLOR_RED}⚠️  ${BUILD_FAILURES} Build(s) Failed${COLOR_RESET}"
fi
echo -e "${COLOR_BLUE}========================================${COLOR_RESET}"
echo -e "${COLOR_CYAN}Branch:${COLOR_RESET}     ${BRANCH}"
echo -e "${COLOR_CYAN}Commit:${COLOR_RESET}     ${COMMIT_SHA}"
echo -e "${COLOR_CYAN}Services:${COLOR_RESET}   ${SERVICES_TO_BUILD[*]}"
echo -e "${COLOR_BLUE}========================================${COLOR_RESET}"

if [ $BUILD_FAILURES -gt 0 ]; then
    exit 1
fi

exit 0
