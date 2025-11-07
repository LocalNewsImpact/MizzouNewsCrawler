#!/bin/bash
# Deploy Argo workflows to staging or production

set -euo pipefail

ENVIRONMENT="${1:-staging}"

if [[ "$ENVIRONMENT" != "staging" && "$ENVIRONMENT" != "production" ]]; then
    echo "Usage: $0 [staging|production]"
    echo "Example: $0 staging"
    exit 1
fi

echo "🚀 Deploying to $ENVIRONMENT..."

# Validate first
echo "Step 1: Running CI validations..."
python3 - <<'EOF'
import yaml
import re
from pathlib import Path
import sys

errors = []

SCHEMAS = {
    'candidate_links': {
        'id', 'url', 'source', 'discovered_at', 'status', 'created_at',
        'dataset_id', 'source_id'
    },
    'articles': {
        'id', 'candidate_link_id', 'url', 'title', 'status', 
        'created_at', 'extracted_at'
    }
}

for yaml_file in Path('k8s/argo').glob('**/*.yaml'):
    with open(yaml_file) as f:
        content = f.read()
    
    # Check for article_id in candidate_links
    if 'article_id' in content and 'candidate_links' in content:
        if re.search(r'candidate_links.*article_id', content, re.IGNORECASE | re.DOTALL):
            errors.append(f"{yaml_file}: candidate_links has no article_id column")
    
    # Check for invalid --exhaust-queue flag
    if '--exhaust-queue' in content:
        errors.append(f"{yaml_file}: Invalid --exhaust-queue flag")

if errors:
    print("❌ Validation failed:")
    for e in errors:
        print(f"  {e}")
    sys.exit(1)
else:
    print("✅ Validation passed")
EOF

if [[ $? -ne 0 ]]; then
    echo "❌ Validation failed. Fix errors before deploying."
    exit 1
fi

# Apply to environment
echo "Step 2: Applying to $ENVIRONMENT namespace..."

if [[ "$ENVIRONMENT" == "staging" ]]; then
    # Create namespace if it doesn't exist
    kubectl create namespace staging --dry-run=client -o yaml | kubectl apply -f -
    
    # Apply with kustomize
    kubectl apply -k k8s/overlays/staging
    
    echo ""
    echo "✅ Deployed to staging!"
    echo ""
    echo "Test with:"
    echo "  argo submit --from workflowtemplate/news-pipeline-template -n staging \\"
    echo "    -p dataset='Test Dataset' -p limit=10"
    echo ""
    echo "Monitor with:"
    echo "  argo logs -n staging @latest -f"
else
    echo "⚠️  Deploying to PRODUCTION. Are you sure? (yes/no)"
    read -r confirm
    if [[ "$confirm" != "yes" ]]; then
        echo "Cancelled."
        exit 0
    fi
    
    kubectl apply -k k8s/overlays/production
    
    echo ""
    echo "✅ Deployed to production!"
fi
