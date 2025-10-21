#!/bin/bash
# Manual Pipeline Trigger - kubectl method
# Usage: ./scripts/trigger_manual_pipeline_kubectl.sh [dataset] [source-limit]
#
# This script submits a workflow using kubectl (no argo CLI required).
# Uses the correct WorkflowTemplate configuration.

set -e

# Default parameters (NO LIMITS - process ALL sources)
DATASET="${1:-Mizzou Missouri State}"
SOURCE_LIMIT="${2:-10000}"  # 10000 = effectively unlimited (process ALL sources)
MAX_ARTICLES="${3:-50}"
DAYS_BACK="${4:-7}"
NAMESPACE="production"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=================================================="
echo "Mizzou News Pipeline - Manual Trigger (kubectl)"
echo -e "==================================================${NC}"
echo ""
echo "Parameters:"
echo "  Dataset: $DATASET"
echo "  Source Limit: $SOURCE_LIMIT (10000 = ALL sources)"
echo "  Max Articles: $MAX_ARTICLES per source"
echo "  Days Back: $DAYS_BACK days"
echo ""

# Check if WorkflowTemplate exists
if ! kubectl get workflowtemplate news-pipeline-template -n $NAMESPACE &> /dev/null; then
    echo -e "${RED}Error: WorkflowTemplate 'news-pipeline-template' not found in $NAMESPACE namespace${NC}"
    exit 1
fi

# Confirmation prompt
read -p "Proceed with manual workflow submission? (y/N): " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo ""
echo -e "${GREEN}Submitting workflow...${NC}"
echo ""

# Create temporary YAML file
TEMP_YAML=$(mktemp)

cat > $TEMP_YAML << EOF
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  generateName: mizzou-news-pipeline-manual-
  labels:
    trigger-type: manual
    trigger-date: "$(date +%Y%m%d)"
spec:
  workflowTemplateRef:
    name: news-pipeline-template
  arguments:
    parameters:
    - name: dataset
      value: "$DATASET"
    - name: source-limit
      value: "$SOURCE_LIMIT"
    - name: max-articles
      value: "$MAX_ARTICLES"
    - name: days-back
      value: "$DAYS_BACK"
    - name: verify-batch-size
      value: "10"
    - name: verify-max-batches
      value: "100"
    - name: extract-limit
      value: "50"
    - name: extract-batches
      value: "40"
    - name: inter-request-min
      value: "5.0"
    - name: inter-request-max
      value: "15.0"
    - name: batch-sleep
      value: "30.0"
    - name: captcha-backoff-base
      value: "1800"
    - name: captcha-backoff-max
      value: "7200"
EOF

# Submit workflow using kubectl
WORKFLOW_NAME=$(kubectl create -n $NAMESPACE -f $TEMP_YAML | awk '{print $1}')

# Clean up
rm $TEMP_YAML

# Extract workflow name
WORKFLOW_NAME=$(echo $WORKFLOW_NAME | sed 's/workflow.argoproj.io\///' | sed 's/ created//')

echo ""
echo -e "${GREEN}Workflow submitted successfully!${NC}"
echo -e "${GREEN}Workflow name: $WORKFLOW_NAME${NC}"
echo ""

# Watch workflow status
echo "Watching workflow status (Ctrl+C to stop watching)..."
echo ""
kubectl get workflow $WORKFLOW_NAME -n $NAMESPACE -w &
WATCH_PID=$!

# Wait a bit then show how to view logs
sleep 5
echo ""
echo "View detailed workflow info:"
echo "  kubectl describe workflow $WORKFLOW_NAME -n $NAMESPACE"
echo ""
echo "View pod logs:"
echo "  kubectl logs -n $NAMESPACE -l workflows.argoproj.io/workflow=$WORKFLOW_NAME --tail=100 -f"
echo ""
echo "Access Argo UI:"
echo "  kubectl -n argo port-forward svc/argo-server 2746:2746"
echo "  Then open: https://localhost:2746"
echo ""

# Keep watching
wait $WATCH_PID
