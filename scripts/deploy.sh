#!/bin/bash
# Automated deployment script for MizzouNewsCrawler services
# This script provides a unified interface for building and deploying services to GKE
#
# Usage:
#   ./scripts/deploy.sh [service] [version] [options]
#
# Examples:
#   ./scripts/deploy.sh processor v1.2.3           # Deploy processor with specific version
#   ./scripts/deploy.sh api v1.3.2 --auto-deploy  # Build and auto-deploy API
#   ./scripts/deploy.sh all latest                 # Deploy all services with latest tag
#
# Services: processor, api, crawler, all
# Options:
#   --auto-deploy    Use auto-deploy Cloud Build config (builds + deploys)
#   --build-only     Only build, don't deploy
#   --skip-tests     Skip running tests before build
#   --dry-run        Show what would be done without doing it

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ID="mizzou-news-crawler"
REGION="us-central1"
CLUSTER_NAME="mizzou-cluster"
CLUSTER_ZONE="us-central1-a"
NAMESPACE="production"

# Parse arguments
SERVICE="${1:-}"
VERSION="${2:-latest}"
AUTO_DEPLOY=false
BUILD_ONLY=false
SKIP_TESTS=false
DRY_RUN=false

shift 2 2>/dev/null || true
while [[ $# -gt 0 ]]; do
    case $1 in
        --auto-deploy)
            AUTO_DEPLOY=true
            shift
            ;;
        --build-only)
            BUILD_ONLY=true
            shift
            ;;
        --skip-tests)
            SKIP_TESTS=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Helper functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

run_command() {
    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}[DRY RUN]${NC} Would execute: $*"
    else
        "$@"
    fi
}

# Validate service
validate_service() {
    case $1 in
        processor|api|crawler|all)
            return 0
            ;;
        *)
            log_error "Invalid service: $1"
            log_info "Valid services: processor, api, crawler, all"
            exit 1
            ;;
    esac
}

# Run tests
run_tests() {
    if [ "$SKIP_TESTS" = true ]; then
        log_warning "Skipping tests (--skip-tests flag set)"
        return 0
    fi

    log_info "Running pytest..."
    if [ "$DRY_RUN" = false ]; then
        if ! venv/bin/pytest tests/ -v --tb=short -x; then
            log_error "Tests failed! Aborting deployment."
            exit 1
        fi
        log_success "All tests passed!"
    else
        log_warning "[DRY RUN] Would run: venv/bin/pytest tests/ -v --tb=short -x"
    fi
}

# Build and deploy a service
deploy_service() {
    local service=$1
    local version=$2
    
    log_info "Deploying ${service} version ${version}..."
    
    if [ "$AUTO_DEPLOY" = true ]; then
        # Use auto-deploy configuration
        local config_file="cloudbuild-${service}-autodeploy.yaml"
        
        if [ ! -f "$config_file" ]; then
            log_error "Auto-deploy config not found: $config_file"
            exit 1
        fi
        
        log_info "Using auto-deploy configuration: $config_file"
        run_command gcloud builds submit \
            --config="$config_file" \
            --region="$REGION" \
            --substitutions="_VERSION=${version}"
        
        log_success "${service} built and deployed automatically!"
        
    elif [ "$BUILD_ONLY" = true ]; then
        # Build only, don't deploy
        local config_file="cloudbuild-${service}.yaml"
        
        log_info "Building only (--build-only flag set)"
        run_command gcloud builds submit \
            --config="$config_file" \
            --region="$REGION"
        
        log_success "${service} built successfully!"
        
    else
        # Build, then manually deploy
        local config_file="cloudbuild-${service}.yaml"
        
        log_info "Building ${service}..."
        run_command gcloud builds submit \
            --config="$config_file" \
            --region="$REGION"
        
        log_success "${service} built successfully!"
        
        # Deploy to Kubernetes
        log_info "Deploying to Kubernetes..."
        case $service in
            processor|api)
                run_command kubectl set image \
                    "deployment/mizzou-${service}" \
                    "${service}=us-central1-docker.pkg.dev/${PROJECT_ID}/mizzou-crawler/${service}:${version}" \
                    --namespace="$NAMESPACE" \
                    --record
                
                log_info "Waiting for rollout..."
                run_command kubectl rollout status \
                    "deployment/mizzou-${service}" \
                    --namespace="$NAMESPACE" \
                    --timeout=5m
                ;;
                
            crawler)
                # CronJob requires patching
                log_info "Updating CronJob image..."
                run_command kubectl patch cronjob/mizzou-crawler \
                    --namespace="$NAMESPACE" \
                    --type=json \
                    -p="[{\"op\": \"replace\", \"path\": \"/spec/jobTemplate/spec/template/spec/containers/0/image\", \"value\": \"us-central1-docker.pkg.dev/${PROJECT_ID}/mizzou-crawler/crawler:${version}\"}]"
                ;;
        esac
        
        log_success "${service} deployed successfully!"
    fi
    
    # Verify deployment
    verify_deployment "$service"
}

# Verify deployment
verify_deployment() {
    local service=$1
    
    log_info "Verifying ${service} deployment..."
    
    case $service in
        processor|api)
            if [ "$DRY_RUN" = false ]; then
                kubectl get pods \
                    --namespace="$NAMESPACE" \
                    -l "app=mizzou-${service}" \
                    -o wide
                
                log_info "Recent logs:"
                kubectl logs \
                    --namespace="$NAMESPACE" \
                    -l "app=mizzou-${service}" \
                    --tail=20 \
                    --since=2m || true
            fi
            ;;
            
        crawler)
            if [ "$DRY_RUN" = false ]; then
                kubectl get cronjob/mizzou-crawler \
                    --namespace="$NAMESPACE" \
                    -o wide
            fi
            ;;
    esac
    
    log_success "${service} verification complete!"
}

# Main execution
main() {
    if [ -z "$SERVICE" ]; then
        log_error "Usage: $0 [service] [version] [options]"
        log_info "Services: processor, api, crawler, all"
        exit 1
    fi
    
    validate_service "$SERVICE"
    
    log_info "========================================="
    log_info "MizzouNewsCrawler Deployment"
    log_info "========================================="
    log_info "Service:      $SERVICE"
    log_info "Version:      $VERSION"
    log_info "Auto-deploy:  $AUTO_DEPLOY"
    log_info "Build only:   $BUILD_ONLY"
    log_info "Skip tests:   $SKIP_TESTS"
    log_info "Dry run:      $DRY_RUN"
    log_info "========================================="
    
    # Run tests first
    run_tests
    
    # Deploy service(s)
    if [ "$SERVICE" = "all" ]; then
        deploy_service "processor" "$VERSION"
        deploy_service "api" "$VERSION"
        deploy_service "crawler" "$VERSION"
    else
        deploy_service "$SERVICE" "$VERSION"
    fi
    
    log_success "========================================="
    log_success "Deployment completed successfully!"
    log_success "========================================="
}

main
