#!/bin/bash
# Apply the Argo WorkflowTemplate FROM THE REPO, with image tags substituted.
#
# Usage: ./update-workflow-template.sh <service-type> <sha> [registry]
# Example: ./update-workflow-template.sh crawler 05f0c40
#
# This script used to read the LIVE template out of the cluster, rewrite only
# its image tags, and push it back -- so nothing else in
# k8s/argo/base-pipeline-workflow.yaml could ever reach production. The cluster
# copy was seeded once by hand and drifted from the repo indefinitely: on
# 2026-07-26 it still carried an extraction-worker cap of 10 (superseded months
# earlier by 702cd559) and lacked the MIZZOU_SQUID_PROXY_URL env from #416, so
# the second proxy was unreachable and a validation run spawned 10 workers
# instead of 2. Both changes were correct in the repo and had never been
# applied.
#
# The rendering logic lives in scripts/render_workflow_template.py so it can be
# unit tested -- it decides what production runs.

set -euo pipefail

SERVICE_TYPE="${1:-}"
NEW_SHA="${2:-}"
# Registry is accepted for backwards compatibility with existing callers; the
# template carries fully-qualified image references, so only the tag changes.
REGISTRY="${3:-}"
TEMPLATE_PATH="${TEMPLATE_PATH:-k8s/argo/base-pipeline-workflow.yaml}"

if [ -z "$SERVICE_TYPE" ] || [ -z "$NEW_SHA" ]; then
  echo "❌ Usage: $0 <service-type> <sha> [registry]"
  exit 1
fi

echo "📦 Service: $SERVICE_TYPE"
echo "🏷️  SHA: $NEW_SHA"
echo "📄 Source of truth: $TEMPLATE_PATH"
echo "🔄 Applying Argo WorkflowTemplate from repo..."

python3 scripts/render_workflow_template.py \
  "$SERVICE_TYPE" "$NEW_SHA" --template "$TEMPLATE_PATH"

echo "✅ Argo WorkflowTemplate now matches the repo, with ${SERVICE_TYPE}:${NEW_SHA}"
