#!/bin/bash
# Setup Google Cloud Deploy for Mizzou News Crawler
# This script initializes Cloud Deploy pipelines and GitHub triggers

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
REPO_OWNER="LocalNewsImpact"
REPO_NAME="MizzouNewsCrawler"

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

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check gcloud
    if ! command -v gcloud &> /dev/null; then
        log_error "gcloud CLI not found. Please install it first."
        exit 1
    fi
    
    # Check authentication
    if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
        log_error "Not authenticated. Run: gcloud auth login"
        exit 1
    fi
    
    # Check project
    CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null)
    if [ "$CURRENT_PROJECT" != "$PROJECT_ID" ]; then
        log_warning "Current project is $CURRENT_PROJECT"
        read -p "Switch to $PROJECT_ID? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            gcloud config set project "$PROJECT_ID"
        else
            log_error "Please set the correct project first"
            exit 1
        fi
    fi
    
    log_success "Prerequisites OK"
}

# Enable required APIs
enable_apis() {
    log_info "Enabling required APIs..."
    
    gcloud services enable \
        cloudbuild.googleapis.com \
        clouddeploy.googleapis.com \
        container.googleapis.com \
        artifactregistry.googleapis.com \
        --project="$PROJECT_ID"
    
    log_success "APIs enabled"
}

# Grant permissions
grant_permissions() {
    log_info "Granting permissions..."
    
    PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
    
    # Cloud Build service account
    CB_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"
    
    # Cloud Deploy service account
    CD_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
    
    log_info "Granting Cloud Build permissions..."
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:${CB_SA}" \
        --role="roles/clouddeploy.releaser" \
        --condition=None 2>/dev/null || true
    
    log_info "Granting Cloud Deploy permissions..."
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:${CD_SA}" \
        --role="roles/container.developer" \
        --condition=None 2>/dev/null || true
    
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:${CD_SA}" \
        --role="roles/iam.serviceAccountUser" \
        --condition=None 2>/dev/null || true
    
    log_success "Permissions granted"
}

# Apply Cloud Deploy configuration
apply_cloud_deploy() {
    log_info "Applying Cloud Deploy configuration..."
    
    if [ ! -f "clouddeploy.yaml" ]; then
        log_error "clouddeploy.yaml not found"
        exit 1
    fi
    
    gcloud deploy apply \
        --file=clouddeploy.yaml \
        --region="$REGION" \
        --project="$PROJECT_ID"
    
    log_success "Cloud Deploy pipeline created"
}

# Create Cloud Build trigger
create_build_trigger() {
    log_info "Creating Cloud Build trigger..."
    
    TRIGGER_NAME="build-on-push"
    
    # Delete if exists
    if gcloud builds triggers describe "$TRIGGER_NAME" --region="$REGION" &>/dev/null; then
        log_warning "Trigger $TRIGGER_NAME already exists. Deleting..."
        gcloud builds triggers delete "$TRIGGER_NAME" --region="$REGION" --quiet
    fi
    
    # Create trigger that builds on any push
    gcloud builds triggers create github \
        --name="$TRIGGER_NAME" \
        --region="$REGION" \
        --repo-name="$REPO_NAME" \
        --repo-owner="$REPO_OWNER" \
        --branch-pattern=".*" \
        --build-config="cloudbuild.yaml" \
        --description="Build images on any branch push" \
        --include-logs-with-status
    
    log_success "Build trigger created"
    log_info "  → Builds on ALL branches"
    log_info "  → Auto-deploys only when pushing to 'main'"
    log_info "  → Feature branches build but don't deploy"
}

# Display next steps
show_next_steps() {
    echo ""
    log_success "========================================="
    log_success "Cloud Deploy Setup Complete!"
    log_success "========================================="
    echo ""
    log_info "Deployment Workflow:"
    echo ""
    echo "  1️⃣  Push to GitHub (any branch)"
    echo "     └─> Builds Docker images automatically"
    echo ""
    echo "  2️⃣  On main branch: Auto-creates release & deploys"
    echo "     └─> Cloud Deploy → Production"
    echo ""
    echo "  3️⃣  On feature branch: Build only (manual deploy)"
    echo "     └─> Use: gcloud deploy releases create ..."
    echo ""
    log_info "View Cloud Deploy:"
    echo "  https://console.cloud.google.com/deploy/delivery-pipelines?project=$PROJECT_ID"
    echo ""
    log_info "View Cloud Build:"
    echo "  https://console.cloud.google.com/cloud-build/builds?project=$PROJECT_ID"
    echo ""
    log_info "Manual deployment from feature branch:"
    echo "  gcloud deploy releases create release-\$(git rev-parse --short HEAD) \\"
    echo "    --delivery-pipeline=mizzou-news-crawler \\"
    echo "    --region=$REGION \\"
    echo "    --images=processor=us-central1-docker.pkg.dev/$PROJECT_ID/mizzou-news-crawler/processor:latest,api=us-central1-docker.pkg.dev/$PROJECT_ID/mizzou-news-crawler/api:latest,crawler=us-central1-docker.pkg.dev/$PROJECT_ID/mizzou-news-crawler/crawler:latest"
    echo ""
}

# Main execution
main() {
    echo ""
    log_info "========================================="
    log_info "Google Cloud Deploy Setup"
    log_info "========================================="
    echo ""
    
    check_prerequisites
    enable_apis
    grant_permissions
    apply_cloud_deploy
    create_build_trigger
    show_next_steps
}

main
