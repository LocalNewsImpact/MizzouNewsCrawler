#!/bin/bash
set -euo pipefail

# Utility script for keeping k8s/versions.env in sync with the latest images.
#
# Usage examples:
#   ./scripts/update-versions-env.sh --processor abc1234 --api abc1234
#   ./scripts/update-versions-env.sh --file other.env --crawler deadbeef
#
# Supported flags:
#   --processor <sha>   Update PROCESSOR_TAG
#   --crawler <sha>     Update CRAWLER_TAG
#   --api <sha>         Update API_TAG
#   --enrichment <sha>  Update ENRICHMENT_TAG
#   --file <path>       Override versions file (default: k8s/versions.env)

VERSIONS_FILE="k8s/versions.env"
PROCESSOR_SHA=""
CRAWLER_SHA=""
API_SHA=""
ENRICHMENT_SHA=""

usage() {
    cat <<'EOF'
update-versions-env.sh --processor <sha> [--crawler <sha>] [--api <sha>] [--enrichment <sha>] [--file <path>]

Updates one or more export entries inside k8s/versions.env so other tooling (kubectl apply,
local scripts, etc.) always reference the latest image tags.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --processor)
            [[ $# -ge 2 ]] || { echo "❌ --processor requires a value" >&2; exit 1; }
            PROCESSOR_SHA="$2"
            shift 2
            ;;
        --crawler)
            [[ $# -ge 2 ]] || { echo "❌ --crawler requires a value" >&2; exit 1; }
            CRAWLER_SHA="$2"
            shift 2
            ;;
        --api)
            [[ $# -ge 2 ]] || { echo "❌ --api requires a value" >&2; exit 1; }
            API_SHA="$2"
            shift 2
            ;;
        --enrichment)
            [[ $# -ge 2 ]] || { echo "❌ --enrichment requires a value" >&2; exit 1; }
            ENRICHMENT_SHA="$2"
            shift 2
            ;;
        --file)
            [[ $# -ge 2 ]] || { echo "❌ --file requires a value" >&2; exit 1; }
            VERSIONS_FILE="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "❌ Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if [[ -z "$PROCESSOR_SHA" && -z "$CRAWLER_SHA" && -z "$API_SHA" && -z "$ENRICHMENT_SHA" ]]; then
    echo "❌ At least one of --processor, --crawler, --api, or --enrichment must be provided" >&2
    usage >&2
    exit 1
fi

if [[ ! -f "$VERSIONS_FILE" ]]; then
    echo "❌ Versions file not found: $VERSIONS_FILE" >&2
    exit 1
fi

update_var() {
    local var_name=$1
    local new_value=$2
    local file_path=$3

    python3 - "$file_path" "$var_name" "$new_value" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
var = sys.argv[2]
value = sys.argv[3]
lines = []
if path.exists():
    lines = path.read_text().splitlines()
updated = False
for idx, line in enumerate(lines):
    if line.startswith(f"export {var}="):
        lines[idx] = f"export {var}={value}"
        updated = True
        break
if not updated:
    lines.append(f"export {var}={value}")
path.write_text("\n".join(lines) + "\n")
PY
}

# Function to update image tags in Argo workflow YAML
update_argo_workflow() {
    local service=$1
    local new_sha=$2
    local argo_file="k8s/argo/base-pipeline-workflow.yaml"

    if [[ ! -f "$argo_file" ]]; then
        echo "⚠️  Argo workflow file not found: $argo_file"
        return
    fi

    # Update image tags in Argo workflow (matches pattern: image:.../<service>:<sha>)
    # Use portable sed syntax (works on both macOS and Linux)
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s|\(us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/${service}:\)[a-f0-9]\{7\}|\1${new_sha}|g" "$argo_file"
    else
        sed -i "s|\(us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/${service}:\)[a-f0-9]\{7\}|\1${new_sha}|g" "$argo_file"
    fi
    echo "✅ Updated Argo workflow ${service} image to $new_sha"
}

if [[ -n "$PROCESSOR_SHA" ]]; then
    update_var "PROCESSOR_TAG" "$PROCESSOR_SHA" "$VERSIONS_FILE"
    update_argo_workflow "processor" "$PROCESSOR_SHA"
    echo "✅ Updated PROCESSOR_TAG to $PROCESSOR_SHA"
fi

if [[ -n "$CRAWLER_SHA" ]]; then
    update_var "CRAWLER_TAG" "$CRAWLER_SHA" "$VERSIONS_FILE"
    update_argo_workflow "crawler" "$CRAWLER_SHA"
    echo "✅ Updated CRAWLER_TAG to $CRAWLER_SHA"
fi

if [[ -n "$API_SHA" ]]; then
    update_var "API_TAG" "$API_SHA" "$VERSIONS_FILE"
    echo "✅ Updated API_TAG to $API_SHA"
fi

if [[ -n "$ENRICHMENT_SHA" ]]; then
    update_var "ENRICHMENT_TAG" "$ENRICHMENT_SHA" "$VERSIONS_FILE"
    echo "✅ Updated ENRICHMENT_TAG to $ENRICHMENT_SHA"
fi
