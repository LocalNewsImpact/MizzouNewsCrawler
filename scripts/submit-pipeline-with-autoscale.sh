#!/usr/bin/env bash
# Submit Argo workflow with dynamic extraction parallelism based on backlog
#
# Usage:
#   ./scripts/submit-pipeline-with-autoscale.sh
#   ./scripts/submit-pipeline-with-autoscale.sh --extraction-only

set -euo pipefail

# Calculate optimal parallelism
PARALLELISM=$(python scripts/calculate-extraction-parallelism.py)

echo "📊 Submitting workflow with $PARALLELISM extraction workers"

# Check for extraction-only mode
if [[ "${1:-}" == "--extraction-only" ]]; then
    echo "🎯 Extraction-only mode (skipping discovery, entity extraction, labeling)"
    argo submit -n production \
        --from cronwf/mizzou-news-pipeline \
        --parameter skip_discovery=true \
        --parameter skip_entity_extraction=true \
        --parameter skip_labeling=true \
        --parameter extraction-parallelism="$PARALLELISM" \
        --name "extraction-auto-$(date +%s)"
else
    echo "🔄 Full pipeline mode (discovery + extraction + processing)"
    argo submit -n production \
        --from cronwf/mizzou-news-pipeline \
        --parameter extraction-parallelism="$PARALLELISM"
fi
