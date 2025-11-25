#!/bin/bash
# Run wire detection verification in production pod

set -e

# Default values
SAMPLE_SIZE=1000
NAMESPACE="production"
POD_TYPE="processor"  # or "api"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --sample-size)
            SAMPLE_SIZE="$2"
            shift 2
            ;;
        --namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        --pod-type)
            POD_TYPE="$2"
            shift 2
            ;;
        --sources)
            SOURCES="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "================================"
echo "Wire Detection Verification"
echo "================================"
echo "Namespace: $NAMESPACE"
echo "Pod type: $POD_TYPE"
echo "Sample size: $SAMPLE_SIZE"
echo "Sources: ${SOURCES:-all}"
echo ""

# Get the pod name
echo "Finding ${POD_TYPE} pod..."
POD_NAME=$(kubectl get pods -n $NAMESPACE -l app=mizzou-${POD_TYPE} -o jsonpath='{.items[0].metadata.name}')

if [ -z "$POD_NAME" ]; then
    echo "ERROR: No ${POD_TYPE} pod found in ${NAMESPACE} namespace"
    exit 1
fi

echo "Using pod: $POD_NAME"
echo ""

# Build the command
CMD="python scripts/verify_wire_detection.py --sample-size $SAMPLE_SIZE"
if [ -n "$SOURCES" ]; then
    CMD="$CMD --sources $SOURCES"
fi

echo "Running verification..."
echo "Command: $CMD"
echo ""

# Run the script in the pod
kubectl exec -n $NAMESPACE $POD_NAME -- $CMD

echo ""
echo "================================"
echo "Retrieving output files..."
echo "================================"

# Copy the CSV files from the pod
kubectl cp $NAMESPACE/$POD_NAME:wire_to_local.csv ./wire_to_local_prod.csv 2>/dev/null && \
    echo "✓ Downloaded wire_to_local_prod.csv" || \
    echo "⚠ No wire_to_local.csv found (no changes detected)"

kubectl cp $NAMESPACE/$POD_NAME:local_to_wire.csv ./local_to_wire_prod.csv 2>/dev/null && \
    echo "✓ Downloaded local_to_wire_prod.csv" || \
    echo "⚠ No local_to_wire.csv found (no changes detected)"

echo ""
echo "================================"
echo "Verification complete!"
echo "================================"
echo "Check the following files for results:"
echo "  - wire_to_local_prod.csv"
echo "  - local_to_wire_prod.csv"
