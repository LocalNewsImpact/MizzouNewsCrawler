#!/bin/bash
# Manual Pipeline Trigger Script
# Usage: ./scripts/trigger_manual_pipeline.sh [dataset] [source-limit]
#
# This script submits a workflow using the correct WorkflowTemplate configuration.
# The CronWorkflow runs automatically every 6 hours, so manual triggers should be rare.

set -e

# Default parameters (NO LIMITS - process ALL sources)
DATASET="${1:-Mizzou Missouri State}"
SOURCE_LIMIT="${2:-}"  # Empty = no limit, process ALL sources
MAX_ARTICLES="${3:-50}"
DAYS_BACK="${4:-7}"
NAMESPACE="production"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=================================================="
echo "Mizzou News Pipeline - Manual Trigger"
echo -e "==================================================${NC}"
echo ""
echo "This will submit a workflow to the production namespace."
echo ""
echo "Parameters:"
echo "  Dataset: $DATASET"
if [ -n "$SOURCE_LIMIT" ]; then
    echo "  Source Limit: $SOURCE_LIMIT sources"
else
    echo "  Source Limit: ALL sources (no limit)"
fi
echo "  Max Articles: $MAX_ARTICLES per source"
echo "  Days Back: $DAYS_BACK days"
echo ""
echo -e "${YELLOW}Note: CronWorkflow runs automatically every 6 hours.${NC}"
echo -e "${YELLOW}Manual triggers should only be needed for testing or recovery.${NC}"
echo ""

# Check if argo CLI is installed
if ! command -v argo &> /dev/null; then
    echo -e "${RED}Error: argo CLI not found!${NC}"
    echo ""
    echo "Install with: brew install argo"
    echo "Or use kubectl method below"
    exit 1
fi

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

# Submit workflow using Argo CLI
if [ -n "$SOURCE_LIMIT" ]; then
  argo submit -n $NAMESPACE \
    --from workflowtemplate/news-pipeline-template \
    --parameter dataset="$DATASET" \
    --parameter source-limit="$SOURCE_LIMIT" \
    --parameter max-articles="$MAX_ARTICLES" \
    --parameter days-back="$DAYS_BACK" \
    --parameter verify-batch-size="10" \
    --parameter verify-max-batches="100" \
    --parameter extract-limit="50" \
    --parameter extract-batches="40" \
    --parameter inter-request-min="5.0" \
    --parameter inter-request-max="15.0" \
    --parameter batch-sleep="30.0" \
    --parameter captcha-backoff-base="1800" \
    --parameter captcha-backoff-max="7200" \
    --watch
else
  argo submit -n $NAMESPACE \
    --from workflowtemplate/news-pipeline-template \
    --parameter dataset="$DATASET" \
    --parameter max-articles="$MAX_ARTICLES" \
    --parameter days-back="$DAYS_BACK" \
    --parameter verify-batch-size="10" \
    --parameter verify-max-batches="100" \
    --parameter extract-limit="50" \
    --parameter extract-batches="40" \
    --parameter inter-request-min="5.0" \
    --parameter inter-request-max="15.0" \
    --parameter batch-sleep="30.0" \
    --parameter captcha-backoff-base="1800" \
    --parameter captcha-backoff-max="7200" \
    --watch
fi

echo ""
echo -e "${GREEN}Workflow submitted successfully!${NC}"
echo ""
echo "Monitor workflow:"
echo "  kubectl get workflows -n $NAMESPACE -w"
echo ""
echo "View logs:"
echo "  argo logs -n $NAMESPACE @latest"
echo ""
echo "Access Argo UI:"
echo "  kubectl -n argo port-forward svc/argo-server 2746:2746"
echo "  Then open: https://localhost:2746"
echo ""
