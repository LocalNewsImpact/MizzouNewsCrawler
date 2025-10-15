#!/bin/bash
# Deploy Argo Workflows for pipeline orchestration
# This script deploys Argo Workflows and the Mizzou/Lehigh pipeline workflows

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
NAMESPACE="${NAMESPACE:-production}"
ARGO_VERSION="${ARGO_VERSION:-v3.5.0}"
DRY_RUN="${DRY_RUN:-false}"
SKIP_ARGO_INSTALL="${SKIP_ARGO_INSTALL:-false}"

echo "=================================================="
echo "Argo Workflows Deployment Script"
echo "=================================================="
echo "Namespace: ${NAMESPACE}"
echo "Argo Version: ${ARGO_VERSION}"
echo "Dry Run: ${DRY_RUN}"
echo "Skip Argo Install: ${SKIP_ARGO_INSTALL}"
echo "=================================================="
echo ""

# Function to print colored messages
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if kubectl is available
check_kubectl() {
    if ! command -v kubectl &> /dev/null; then
        print_error "kubectl not found. Please install kubectl."
        exit 1
    fi
    print_info "kubectl found: $(kubectl version --client --short 2>/dev/null || kubectl version --client)"
}

# Function to check if namespace exists
check_namespace() {
    if ! kubectl get namespace "${NAMESPACE}" &> /dev/null; then
        print_error "Namespace ${NAMESPACE} does not exist."
        echo "Create it with: kubectl create namespace ${NAMESPACE}"
        exit 1
    fi
    print_info "Namespace ${NAMESPACE} exists"
}

# Function to install Argo Workflows
install_argo() {
    if [ "${SKIP_ARGO_INSTALL}" = "true" ]; then
        print_info "Skipping Argo Workflows installation (SKIP_ARGO_INSTALL=true)"
        return
    fi

    print_info "Installing Argo Workflows ${ARGO_VERSION}..."
    
    if [ "${DRY_RUN}" = "true" ]; then
        print_info "[DRY RUN] Would install Argo Workflows from:"
        print_info "  https://github.com/argoproj/argo-workflows/releases/download/${ARGO_VERSION}/install.yaml"
        return
    fi
    
    # Create argo namespace if it doesn't exist
    if ! kubectl get namespace argo &> /dev/null; then
        kubectl create namespace argo
        print_info "Created namespace: argo"
    fi
    
    # Install Argo Workflows
    kubectl apply -n argo -f "https://github.com/argoproj/argo-workflows/releases/download/${ARGO_VERSION}/install.yaml"
    
    print_info "Waiting for Argo Workflows controller to be ready..."
    kubectl wait --for=condition=available --timeout=300s -n argo deployment/workflow-controller
    kubectl wait --for=condition=available --timeout=300s -n argo deployment/argo-server
    
    print_info "Argo Workflows installed successfully"
}

# Function to deploy RBAC configuration
deploy_rbac() {
    print_info "Deploying RBAC configuration..."
    
    local rbac_file="k8s/argo/rbac.yaml"
    
    if [ ! -f "${rbac_file}" ]; then
        print_error "RBAC file not found: ${rbac_file}"
        exit 1
    fi
    
    if [ "${DRY_RUN}" = "true" ]; then
        print_info "[DRY RUN] Would apply RBAC from: ${rbac_file}"
        kubectl apply -f "${rbac_file}" --dry-run=client
        return
    fi
    
    kubectl apply -f "${rbac_file}"
    print_info "RBAC configuration deployed"
}

# Function to deploy workflow
deploy_workflow() {
    local workflow_name=$1
    local workflow_file=$2
    
    print_info "Deploying ${workflow_name} workflow..."
    
    if [ ! -f "${workflow_file}" ]; then
        print_error "Workflow file not found: ${workflow_file}"
        exit 1
    fi
    
    if [ "${DRY_RUN}" = "true" ]; then
        print_info "[DRY RUN] Would apply workflow from: ${workflow_file}"
        kubectl apply -f "${workflow_file}" --dry-run=client
        return
    fi
    
    kubectl apply -f "${workflow_file}"
    print_info "${workflow_name} workflow deployed"
}

# Function to verify deployment
verify_deployment() {
    print_info "Verifying deployment..."
    
    if [ "${DRY_RUN}" = "true" ]; then
        print_info "[DRY RUN] Skipping verification"
        return
    fi
    
    # Check if CronWorkflows were created
    local mizzou_exists=$(kubectl get cronworkflow mizzou-news-pipeline -n ${NAMESPACE} &> /dev/null && echo "yes" || echo "no")
    local lehigh_exists=$(kubectl get cronworkflow lehigh-news-pipeline -n ${NAMESPACE} &> /dev/null && echo "yes" || echo "no")
    
    if [ "${mizzou_exists}" = "yes" ]; then
        print_info "✓ Mizzou pipeline workflow created"
        kubectl get cronworkflow mizzou-news-pipeline -n ${NAMESPACE}
    else
        print_error "✗ Mizzou pipeline workflow NOT found"
    fi
    
    if [ "${lehigh_exists}" = "yes" ]; then
        print_info "✓ Lehigh pipeline workflow created"
        kubectl get cronworkflow lehigh-news-pipeline -n ${NAMESPACE}
    else
        print_error "✗ Lehigh pipeline workflow NOT found"
    fi
    
    # Check ServiceAccount
    if kubectl get serviceaccount argo-workflow -n ${NAMESPACE} &> /dev/null; then
        print_info "✓ ServiceAccount argo-workflow exists"
    else
        print_error "✗ ServiceAccount argo-workflow NOT found"
    fi
}

# Function to display next steps
display_next_steps() {
    echo ""
    echo "=================================================="
    echo "Deployment Complete!"
    echo "=================================================="
    echo ""
    echo "Next Steps:"
    echo ""
    echo "1. Access Argo UI:"
    echo "   kubectl -n argo port-forward svc/argo-server 2746:2746"
    echo "   Then open: https://localhost:2746"
    echo ""
    echo "2. List CronWorkflows:"
    echo "   kubectl get cronworkflow -n ${NAMESPACE}"
    echo ""
    echo "3. View workflow history:"
    echo "   kubectl get workflows -n ${NAMESPACE}"
    echo ""
    echo "4. Watch workflow execution:"
    echo "   kubectl get workflows -n ${NAMESPACE} -w"
    echo ""
    echo "5. View workflow logs:"
    echo "   kubectl logs -n ${NAMESPACE} -l workflows.argoproj.io/workflow=<workflow-name>"
    echo ""
    echo "6. Suspend CronWorkflow (stop scheduled runs):"
    echo "   kubectl patch cronworkflow mizzou-news-pipeline -n ${NAMESPACE} -p '{\"spec\":{\"suspend\":true}}'"
    echo ""
    echo "7. Resume CronWorkflow:"
    echo "   kubectl patch cronworkflow mizzou-news-pipeline -n ${NAMESPACE} -p '{\"spec\":{\"suspend\":false}}'"
    echo ""
    echo "=================================================="
}

# Main execution
main() {
    print_info "Starting Argo Workflows deployment..."
    
    # Pre-flight checks
    check_kubectl
    check_namespace
    
    # Install Argo Workflows
    install_argo
    
    # Deploy RBAC
    deploy_rbac
    
    # Deploy workflows
    deploy_workflow "Mizzou" "k8s/argo/mizzou-pipeline-workflow.yaml"
    deploy_workflow "Lehigh" "k8s/argo/lehigh-pipeline-workflow.yaml"
    
    # Verify deployment
    verify_deployment
    
    # Display next steps
    if [ "${DRY_RUN}" != "true" ]; then
        display_next_steps
    fi
    
    print_info "Deployment script completed successfully"
}

# Run main function
main
