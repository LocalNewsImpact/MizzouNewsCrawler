#!/bin/bash
# Robust CLI wrapper using dedicated CLI deployment
# This script manages a dedicated Kubernetes deployment for CLI commands

set -e

NAMESPACE="${NAMESPACE:-production}"
DEPLOYMENT="mizzou-cli"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

usage() {
    echo "Usage: $0 <command> [args...]"
    echo ""
    echo "Examples:"
    echo "  $0 pipeline-status"
    echo "  $0 pipeline-status --detailed"
    echo "  $0 extract --limit 20"
    echo "  $0 discover-urls --source-limit 10"
    echo ""
    echo "Special commands:"
    echo "  $0 shell                 # Open interactive shell"
    echo "  $0 scale-down            # Scale CLI deployment to 0"
    echo ""
    exit 1
}

ensure_deployment_exists() {
    if ! kubectl get deployment "$DEPLOYMENT" -n "$NAMESPACE" &>/dev/null; then
        echo -e "${YELLOW}⚠️  CLI deployment not found. Creating it...${NC}"
        kubectl apply -f k8s/cli-deployment.yaml
        echo -e "${GREEN}✓ CLI deployment created${NC}"
    fi
}

ensure_pod_ready() {
    local replicas=$(kubectl get deployment "$DEPLOYMENT" -n "$NAMESPACE" -o jsonpath='{.status.replicas}' 2>/dev/null || echo "0")
    
    if [ "$replicas" = "0" ] || [ -z "$replicas" ]; then
        echo -e "${YELLOW}⚙️  Scaling CLI deployment to 1 replica...${NC}"
        kubectl scale deployment "$DEPLOYMENT" --replicas=1 -n "$NAMESPACE"
        
        echo "⏳ Waiting for pod to be ready..."
        kubectl wait --for=condition=ready pod -l app="$DEPLOYMENT" -n "$NAMESPACE" --timeout=60s
        echo -e "${GREEN}✓ CLI pod ready${NC}"
    else
        # Check if pod is ready
        if ! kubectl get pod -l app="$DEPLOYMENT" -n "$NAMESPACE" -o jsonpath='{.items[0].status.conditions[?(@.type=="Ready")].status}' 2>/dev/null | grep -q "True"; then
            echo "⏳ Waiting for pod to be ready..."
            kubectl wait --for=condition=ready pod -l app="$DEPLOYMENT" -n "$NAMESPACE" --timeout=60s
        fi
    fi
}

scale_down() {
    echo -e "${YELLOW}⚙️  Scaling CLI deployment to 0 replicas...${NC}"
    kubectl scale deployment "$DEPLOYMENT" --replicas=0 -n "$NAMESPACE"
    echo -e "${GREEN}✓ CLI deployment scaled down${NC}"
}

# Handle special commands
if [ "$1" = "scale-down" ]; then
    ensure_deployment_exists
    scale_down
    exit 0
fi

if [ "$1" = "shell" ]; then
    ensure_deployment_exists
    ensure_pod_ready
    echo -e "${GREEN}🐚 Opening interactive shell in CLI pod...${NC}"
    kubectl exec -it deploy/"$DEPLOYMENT" -n "$NAMESPACE" -- bash
    exit 0
fi

if [ $# -eq 0 ]; then
    usage
fi

# Run CLI command
ensure_deployment_exists
ensure_pod_ready

echo -e "${GREEN}▶️  Running: python -m src.cli.main $*${NC}"
echo ""

kubectl exec deploy/"$DEPLOYMENT" -n "$NAMESPACE" -- python -m src.cli.main "$@"
EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ Command completed successfully${NC}"
else
    echo -e "${YELLOW}⚠️  Command exited with code $EXIT_CODE${NC}"
fi

echo ""
echo "💡 Tip: Run '$0 scale-down' to save resources when done"

exit $EXIT_CODE
