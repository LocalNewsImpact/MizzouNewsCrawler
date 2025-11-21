#!/bin/bash
# Shared script for updating Argo WorkflowTemplate after service deployments
# Usage: ./shared-post-deploy.sh <service-type> <sha> <registry>
# Example: ./shared-post-deploy.sh crawler 05f0c40 us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler

set -euo pipefail

SERVICE_TYPE="${1:-}"
NEW_SHA="${2:-}"
REGISTRY="${3:-us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler}"

if [ -z "$SERVICE_TYPE" ] || [ -z "$NEW_SHA" ]; then
  echo "❌ Usage: $0 <service-type> <sha> [registry]"
  exit 1
fi

echo "📦 Service: $SERVICE_TYPE"
echo "🏷️  SHA: $NEW_SHA"
echo "🔄 Updating Argo WorkflowTemplate..."

# Use Python to update the workflow template
python3 << 'PYTHON_EOF' "$SERVICE_TYPE" "$NEW_SHA" "$REGISTRY"
import subprocess, json, sys, os

service_type = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('SERVICE_TYPE', '')
new_sha = sys.argv[2] if len(sys.argv) > 2 else os.environ.get('NEW_SHA', '')
registry = sys.argv[3] if len(sys.argv) > 3 else os.environ.get('REGISTRY', 'us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler')

if not service_type or not new_sha:
    print("❌ Missing SERVICE_TYPE or NEW_SHA")
    sys.exit(1)

print(f"Updating {service_type} images to {new_sha}...")

# Get the workflow template
try:
    result = subprocess.run(
        ["kubectl", "get", "workflowtemplate", "news-pipeline-template", "-n", "production", "-o", "json"],
        capture_output=True, text=True, check=True
    )
    wf = json.loads(result.stdout)
except subprocess.CalledProcessError as e:
    print(f"❌ Failed to get workflow template: {e.stderr}")
    sys.exit(1)

# Update images based on service type
updated_count = 0
for template in wf['spec']['templates']:
    if 'container' in template and 'image' in template['container']:
        img = template['container']['image']
        
        # Update crawler images
        if service_type == 'crawler' and f'{service_type}:' in img:
            template['container']['image'] = f"{registry}/crawler:{new_sha}"
            print(f"  ✓ Updated {template['name']}: crawler:{new_sha}")
            updated_count += 1
        
        # Update processor images
        elif service_type == 'processor' and f'{service_type}:' in img:
            template['container']['image'] = f"{registry}/processor:{new_sha}"
            print(f"  ✓ Updated {template['name']}: processor:{new_sha}")
            updated_count += 1

if updated_count == 0:
    print(f"⚠️  No {service_type} images found in workflow template")
    sys.exit(0)

# Apply the updated workflow
try:
    proc = subprocess.Popen(
        ["kubectl", "apply", "-f", "-"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    stdout, stderr = proc.communicate(json.dumps(wf))
    
    if proc.returncode != 0:
        print(f"❌ Failed to apply workflow template: {stderr}")
        sys.exit(1)
    
    print(stdout)
    print(f"✅ Updated {updated_count} workflow templates with {service_type}:{new_sha}")
except Exception as e:
    print(f"❌ Error applying workflow: {e}")
    sys.exit(1)
PYTHON_EOF

echo "✅ Argo WorkflowTemplate updated successfully"
echo "   Next workflow run will use ${SERVICE_TYPE}:${NEW_SHA}"
