#!/bin/bash
# Setup Cloud Build triggers for automated CI/CD
# This script creates triggers:
#   - Automatic deployment on push to main branch (production)
#   - Manual triggers for feature branches (testing)
#
# Usage: ./scripts/setup-triggers.sh

set -euo pipefail

# Configuration
PROJECT_ID="mizzou-news-crawler"
REPO_OWNER="LocalNewsImpact"
REPO_NAME="MizzouNewsCrawler"
MAIN_BRANCH="main"

# Colors
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

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if gcloud is authenticated
check_auth() {
    log_info "Checking gcloud authentication..."
    if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
        log_error "Not authenticated with gcloud. Run: gcloud auth login"
        exit 1
    fi
    log_success "Authenticated"
}

# Check if project is set
check_project() {
    log_info "Checking project configuration..."
    CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null)
    if [ "$CURRENT_PROJECT" != "$PROJECT_ID" ]; then
        log_warning "Current project is $CURRENT_PROJECT, not $PROJECT_ID"
        read -p "Set project to $PROJECT_ID? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            gcloud config set project "$PROJECT_ID"
        fi
    fi
    log_success "Project: $PROJECT_ID"
}

# Grant necessary permissions to Cloud Build service account
grant_permissions() {
    log_info "Granting permissions to Cloud Build service account..."
    
    PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
    SERVICE_ACCOUNT="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"
    
    log_info "Service account: $SERVICE_ACCOUNT"
    
    # Grant Kubernetes Engine Developer role
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:${SERVICE_ACCOUNT}" \
        --role="roles/container.developer" \
        --condition=None \
        2>/dev/null || log_warning "Permission may already exist"
    
    # Grant Service Account User role
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:${SERVICE_ACCOUNT}" \
        --role="roles/iam.serviceAccountUser" \
        --condition=None \
        2>/dev/null || log_warning "Permission may already exist"
    
    log_success "Permissions granted"
}

# Create or update a trigger
create_trigger() {
    local name=$1
    local service=$2
    local branch=$3
    local require_approval=${4:-false}
    local version_sub=${5:-"latest"}
    
    log_info "Creating trigger: $name"
    
    # Check if trigger already exists
    if gcloud builds triggers describe "$name" &>/dev/null; then
        log_warning "Trigger $name already exists. Deleting..."
        gcloud builds triggers delete "$name" --quiet
    fi
    
    # Build the command
    CMD=(
        gcloud builds triggers create github
        --name="$name"
        --repo-name="$REPO_NAME"
        --repo-owner="$REPO_OWNER"
        --branch-pattern="^${branch}$"
        --build-config="cloudbuild-${service}-autodeploy.yaml"
        --description="Auto-build and deploy ${service} on ${branch} branch"
        --include-logs-with-status
        --substitutions="_VERSION=${version_sub}"
    )
    
    # Add approval requirement for production
    if [ "$require_approval" = true ]; then
        CMD+=(--require-approval)
    fi
    
    # Execute the command
    if "${CMD[@]}"; then
        log_success "Created trigger: $name"
    else
        log_error "Failed to create trigger: $name"
        return 1
    fi
}

# Create all triggers
create_all_triggers() {
    log_info "========================================="
    log_info "Creating Cloud Build Triggers"
    log_info "========================================="
    
    # Production triggers (auto-deploy on main branch)
    log_info "Creating production auto-deploy triggers for main branch..."
    log_info "These will automatically deploy when you push to main branch"
    log_info ""
    
    read -p "Create production (main branch) auto-deploy triggers? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        create_trigger "processor-autodeploy-main" "processor" "$MAIN_BRANCH" false '\${BRANCH_NAME}-\${SHORT_SHA}'
        create_trigger "api-autodeploy-main" "api" "$MAIN_BRANCH" false '\${BRANCH_NAME}-\${SHORT_SHA}'
        create_trigger "crawler-autodeploy-main" "crawler" "$MAIN_BRANCH" false '\${BRANCH_NAME}-\${SHORT_SHA}'
        
        log_success "Production triggers created! These auto-deploy on push to main."
    fi
    
    log_info ""
    log_info "========================================="
    log_info "Manual Triggers for Feature Branches"
    log_info "========================================="
    log_info ""
    log_info "Feature branches should use MANUAL triggers."
    log_info "To deploy from a feature branch, run:"
    log_info "  gcloud builds submit --config=cloudbuild-processor-autodeploy.yaml"
    log_info ""
    log_info "Or use the helper script:"
    log_info "  ./scripts/deploy.sh processor v1.2.3 --auto-deploy"
    log_info ""
}

# List created triggers
list_triggers() {
    log_info "========================================="
    log_info "Created Triggers"
    log_info "========================================="
    gcloud builds triggers list --format="table(name,github.owner,github.name,github.branch,filename,disabled)"
}

# Test manual deployment from feature branch
test_manual_deploy() {
    log_info "========================================="
    log_info "Test Manual Deployment"
    log_info "========================================="
    
    read -p "Test manual deployment from current branch? (y/n) " -n 1 -r
    echo
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Skipping manual deployment test"
        return
    fi
    
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
    log_info "Current branch: $CURRENT_BRANCH"
    
    PS3="Select service to deploy: "
    options=("processor" "api" "crawler" "cancel")
    select SERVICE in "${options[@]}"; do
        case $SERVICE in
            "processor"|"api"|"crawler")
                log_info "Deploying $SERVICE from branch $CURRENT_BRANCH..."
                
                if gcloud builds submit \
                    --config="cloudbuild-${SERVICE}-autodeploy.yaml" \
                    --region=us-central1 \
                    --substitutions="_VERSION=${CURRENT_BRANCH}-test"; then
                    
                    log_success "Manual deployment started!"
                    log_info "View logs at: https://console.cloud.google.com/cloud-build/builds?project=$PROJECT_ID"
                    
                    read -p "Stream logs? (y/n) " -n 1 -r
                    echo
                    if [[ $REPLY =~ ^[Yy]$ ]]; then
                        BUILD_ID=$(gcloud builds list --ongoing --limit=1 --format='value(id)')
                        if [ -n "$BUILD_ID" ]; then
                            gcloud builds log "$BUILD_ID" --stream
                        fi
                    fi
                else
                    log_error "Manual deployment failed"
                fi
                break
                ;;
            "cancel")
                log_info "Cancelled"
                break
                ;;
            *)
                log_warning "Invalid option"
                ;;
        esac
    done
}

# Main execution
main() {
    echo -e "${GREEN}"
    cat << "EOF"
╔═══════════════════════════════════════════════════════╗
║   Cloud Build Triggers Setup                         ║
║   Automated CI/CD for MizzouNewsCrawler              ║
╚═══════════════════════════════════════════════════════╝
EOF
    echo -e "${NC}"
    
    check_auth
    check_project
    grant_permissions
    
    echo ""
    create_all_triggers
    
    echo ""
    list_triggers
    
    echo ""
    test_manual_deploy
    
    echo ""
    log_success "========================================="
    log_success "Setup Complete!"
    log_success "========================================="
    log_info ""
    log_info "Deployment Strategy:"
    log_info "  📦 Main branch     → Auto-deploys on git push (production)"
    log_info "  🔧 Feature branches → Manual deployment only"
    log_info ""
    log_info "To deploy from a feature branch:"
    log_info "  gcloud builds submit --config=cloudbuild-processor-autodeploy.yaml"
    log_info ""
    log_info "Or use the helper script:"
    log_info "  ./scripts/deploy.sh processor v1.2.3 --auto-deploy"
    log_info ""
    log_info "To view triggers:"
    log_info "  gcloud builds triggers list"
    log_info ""
    log_info "To view builds:"
    log_info "  gcloud builds list --limit=10"
    log_info ""
}

main
