#!/bin/bash
# Create Cloud Monitoring dashboards for MizzouNewsCrawler

set -e

PROJECT_ID="mizzou-news-crawler"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Creating Cloud Monitoring Dashboards ==="
echo "Project: $PROJECT_ID"
echo ""

# Function to create dashboard
create_dashboard() {
    local dashboard_file=$1
    local dashboard_name=$(basename "$dashboard_file" .json)
    
    echo "Creating dashboard: $dashboard_name"
    
    gcloud monitoring dashboards create \
        --config-from-file="$dashboard_file" \
        --project="$PROJECT_ID" 2>&1 | grep -v "WARNING" || {
        echo "Dashboard may already exist or error occurred"
        echo "Attempting to update instead..."
        
        # Try to update existing dashboard
        # First, list dashboards to find the ID
        dashboard_id=$(gcloud monitoring dashboards list \
            --project="$PROJECT_ID" \
            --filter="displayName:$dashboard_name" \
            --format="value(name)" \
            --limit=1 2>/dev/null || echo "")
        
        if [ -n "$dashboard_id" ]; then
            echo "Found existing dashboard: $dashboard_id"
            echo "Update via UI: https://console.cloud.google.com/monitoring/dashboards"
        fi
    }
    echo ""
}

# Create System Health dashboard
if [ -f "$SCRIPT_DIR/dashboards/system-health.json" ]; then
    create_dashboard "$SCRIPT_DIR/dashboards/system-health.json"
fi

# Create Pipeline Metrics dashboard
if [ -f "$SCRIPT_DIR/dashboards/pipeline-metrics.json" ]; then
    create_dashboard "$SCRIPT_DIR/dashboards/pipeline-metrics.json"
fi

echo "=== Dashboard Creation Complete ==="
echo ""
echo "View dashboards at:"
echo "https://console.cloud.google.com/monitoring/dashboards?project=$PROJECT_ID"
echo ""
echo "Note: Some metrics may not appear until the application emits them."
echo "Custom metrics require instrumentation in the application code."
