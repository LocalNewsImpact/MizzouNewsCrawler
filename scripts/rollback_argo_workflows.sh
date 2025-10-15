#!/bin/bash
# Rollback Argo Workflows deployment
# This script removes Argo Workflows and restores original CronJobs

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
NAMESPACE="${NAMESPACE:-production}"
DRY_RUN="${DRY_RUN:-false}"
KEEP_ARGO="${KEEP_ARGO:-true}"

echo "=================================================="
echo "Argo Workflows Rollback Script"
echo "=================================================="
echo "Namespace: ${NAMESPACE}"
echo "Dry Run: ${DRY_RUN}"
echo "Keep Argo Installation: ${KEEP_ARGO}"
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

# Function to confirm rollback
confirm_rollback() {
    if [ "${DRY_RUN}" = "true" ]; then
        print_info "[DRY RUN] Skipping confirmation"
        return
    fi
    
    echo ""
    print_warning "This will delete the Argo Workflows pipelines."
    print_warning "Original CronJobs will need to be re-enabled manually."
    echo ""
    read -p "Are you sure you want to continue? (yes/no): " -r
    echo ""
    
    if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
        print_info "Rollback cancelled"
        exit 0
    fi
}

# Function to suspend Argo CronWorkflows
suspend_cronworkflows() {
    print_info "Suspending Argo CronWorkflows..."
    
    if [ "${DRY_RUN}" = "true" ]; then
        print_info "[DRY RUN] Would suspend CronWorkflows"
        return
    fi
    
    # Suspend Mizzou pipeline
    if kubectl get cronworkflow mizzou-news-pipeline -n ${NAMESPACE} &> /dev/null; then
        kubectl patch cronworkflow mizzou-news-pipeline -n ${NAMESPACE} -p '{"spec":{"suspend":true}}'
        print_info "Suspended mizzou-news-pipeline"
    fi
    
    # Suspend Lehigh pipeline
    if kubectl get cronworkflow lehigh-news-pipeline -n ${NAMESPACE} &> /dev/null; then
        kubectl patch cronworkflow lehigh-news-pipeline -n ${NAMESPACE} -p '{"spec":{"suspend":true}}'
        print_info "Suspended lehigh-news-pipeline"
    fi
    
    print_info "Waiting 30 seconds to ensure no new workflows are triggered..."
    sleep 30
}

# Function to delete running workflows
delete_running_workflows() {
    print_info "Checking for running workflows..."
    
    if [ "${DRY_RUN}" = "true" ]; then
        print_info "[DRY RUN] Would delete running workflows"
        kubectl get workflows -n ${NAMESPACE} 2>/dev/null || true
        return
    fi
    
    # Get list of running workflows
    local running_workflows=$(kubectl get workflows -n ${NAMESPACE} --field-selector=status.phase=Running -o name 2>/dev/null || echo "")
    
    if [ -z "${running_workflows}" ]; then
        print_info "No running workflows found"
        return
    fi
    
    print_warning "Found running workflows. Deleting them..."
    echo "${running_workflows}" | xargs -I {} kubectl delete {} -n ${NAMESPACE}
    print_info "Running workflows deleted"
}

# Function to delete CronWorkflows
delete_cronworkflows() {
    print_info "Deleting Argo CronWorkflows..."
    
    if [ "${DRY_RUN}" = "true" ]; then
        print_info "[DRY RUN] Would delete CronWorkflows"
        return
    fi
    
    # Delete Mizzou pipeline
    if kubectl get cronworkflow mizzou-news-pipeline -n ${NAMESPACE} &> /dev/null; then
        kubectl delete cronworkflow mizzou-news-pipeline -n ${NAMESPACE}
        print_info "Deleted mizzou-news-pipeline"
    fi
    
    # Delete Lehigh pipeline
    if kubectl get cronworkflow lehigh-news-pipeline -n ${NAMESPACE} &> /dev/null; then
        kubectl delete cronworkflow lehigh-news-pipeline -n ${NAMESPACE}
        print_info "Deleted lehigh-news-pipeline"
    fi
}

# Function to delete RBAC resources
delete_rbac() {
    print_info "Deleting RBAC resources..."
    
    if [ "${DRY_RUN}" = "true" ]; then
        print_info "[DRY RUN] Would delete RBAC resources"
        return
    fi
    
    # Delete RoleBinding
    if kubectl get rolebinding argo-workflow-binding -n ${NAMESPACE} &> /dev/null; then
        kubectl delete rolebinding argo-workflow-binding -n ${NAMESPACE}
        print_info "Deleted RoleBinding argo-workflow-binding"
    fi
    
    # Delete Role
    if kubectl get role argo-workflow-role -n ${NAMESPACE} &> /dev/null; then
        kubectl delete role argo-workflow-role -n ${NAMESPACE}
        print_info "Deleted Role argo-workflow-role"
    fi
    
    # Delete ServiceAccount
    if kubectl get serviceaccount argo-workflow -n ${NAMESPACE} &> /dev/null; then
        kubectl delete serviceaccount argo-workflow -n ${NAMESPACE}
        print_info "Deleted ServiceAccount argo-workflow"
    fi
}

# Function to uninstall Argo Workflows (optional)
uninstall_argo() {
    if [ "${KEEP_ARGO}" = "true" ]; then
        print_info "Keeping Argo Workflows installation (KEEP_ARGO=true)"
        return
    fi
    
    print_warning "Uninstalling Argo Workflows from argo namespace..."
    
    if [ "${DRY_RUN}" = "true" ]; then
        print_info "[DRY RUN] Would uninstall Argo Workflows"
        return
    fi
    
    if kubectl get namespace argo &> /dev/null; then
        kubectl delete namespace argo
        print_info "Deleted argo namespace and all resources"
    else
        print_info "Argo namespace not found, skipping"
    fi
}

# Function to show how to re-enable old CronJobs
show_reenable_instructions() {
    echo ""
    echo "=================================================="
    echo "Rollback Complete!"
    echo "=================================================="
    echo ""
    echo "To re-enable original CronJobs, run:"
    echo ""
    echo "kubectl patch cronjob mizzou-discovery -n ${NAMESPACE} -p '{\"spec\":{\"suspend\":false}}'"
    echo "kubectl patch cronjob mizzou-processor -n ${NAMESPACE} -p '{\"spec\":{\"suspend\":false}}'"
    echo "kubectl patch cronjob mizzou-crawler -n ${NAMESPACE} -p '{\"spec\":{\"suspend\":false}}'"
    echo ""
    echo "Or scale up the processor deployment:"
    echo "kubectl scale deployment mizzou-processor --replicas=1 -n ${NAMESPACE}"
    echo ""
    echo "=================================================="
}

# Main execution
main() {
    print_info "Starting Argo Workflows rollback..."
    
    # Confirm rollback
    confirm_rollback
    
    # Suspend CronWorkflows
    suspend_cronworkflows
    
    # Delete running workflows
    delete_running_workflows
    
    # Delete CronWorkflows
    delete_cronworkflows
    
    # Delete RBAC resources
    delete_rbac
    
    # Optionally uninstall Argo
    uninstall_argo
    
    # Show re-enable instructions
    if [ "${DRY_RUN}" != "true" ]; then
        show_reenable_instructions
    fi
    
    print_info "Rollback script completed successfully"
}

# Run main function
main
