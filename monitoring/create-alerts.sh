#!/bin/bash
# Create Cloud Monitoring alert policies for MizzouNewsCrawler

set -e

PROJECT_ID="mizzou-news-crawler"
PROJECT_NUMBER="145096615031"
NOTIFICATION_CHANNEL=""  # Will be created if needed

echo "=== Creating Cloud Monitoring Alert Policies ==="
echo "Project: $PROJECT_ID"
echo ""

# Check if notification channel exists, create if not
echo "Checking for notification channels..."
existing_channel=$(gcloud alpha monitoring channels list \
    --project="$PROJECT_ID" \
    --filter="displayName:'Email - Admin'" \
    --format="value(name)" \
    --limit=1 2>/dev/null || echo "")

if [ -z "$existing_channel" ]; then
    echo "No notification channel found. Creating email channel..."
    echo "Note: You'll need to verify the email address."
    
    # Prompt for email
    read -p "Enter email address for alerts: " ADMIN_EMAIL
    
    cat > /tmp/notification-channel.json <<EOF
{
  "type": "email",
  "displayName": "Email - Admin",
  "labels": {
    "email_address": "$ADMIN_EMAIL"
  },
  "enabled": true
}
EOF
    
    NOTIFICATION_CHANNEL=$(gcloud alpha monitoring channels create \
        --channel-content-from-file=/tmp/notification-channel.json \
        --project="$PROJECT_ID" \
        --format="value(name)" 2>/dev/null || echo "")
    
    rm /tmp/notification-channel.json
    
    if [ -n "$NOTIFICATION_CHANNEL" ]; then
        echo "✓ Created notification channel: $NOTIFICATION_CHANNEL"
        echo "⚠️  Check email to verify the notification channel"
    else
        echo "❌ Failed to create notification channel"
        exit 1
    fi
else
    NOTIFICATION_CHANNEL="$existing_channel"
    echo "✓ Using existing notification channel: $NOTIFICATION_CHANNEL"
fi

echo ""

# Function to create alert policy
create_alert() {
    local alert_name=$1
    local alert_file=$2
    
    echo "Creating alert policy: $alert_name"
    
    gcloud alpha monitoring policies create \
        --notification-channels="$NOTIFICATION_CHANNEL" \
        --policy-from-file="$alert_file" \
        --project="$PROJECT_ID" 2>&1 | grep -v "WARNING" || {
        echo "Alert policy may already exist"
    }
    echo ""
}

# Critical Alert: Pod Restart Rate
cat > /tmp/alert-pod-restarts.yaml <<'EOF'
displayName: "CRITICAL: High Pod Restart Rate"
documentation:
  content: "Pod restart count > 3 in 10 minutes. Check pod logs and events."
  mimeType: "text/markdown"
conditions:
  - displayName: "Pod restarts > 3 in 10 minutes"
    conditionThreshold:
      filter: |
        resource.type = "k8s_pod"
        AND resource.labels.cluster_name = "mizzou-cluster"
        AND resource.labels.namespace_name = "production"
        AND metric.type = "kubernetes.io/pod/container/restart_count"
      aggregations:
        - alignmentPeriod: "600s"
          perSeriesAligner: "ALIGN_DELTA"
          crossSeriesReducer: "REDUCE_SUM"
          groupByFields:
            - "resource.pod_name"
      comparison: "COMPARISON_GT"
      thresholdValue: 3
      duration: "0s"
combiner: "OR"
enabled: true
alertStrategy:
  autoClose: "1800s"
severity: "CRITICAL"
EOF

create_alert "pod-restarts" "/tmp/alert-pod-restarts.yaml"

# Critical Alert: Cloud SQL CPU High
cat > /tmp/alert-cloudsql-cpu.yaml <<'EOF'
displayName: "CRITICAL: Cloud SQL CPU > 90%"
documentation:
  content: "Cloud SQL CPU utilization > 90%. Consider scaling up the instance."
  mimeType: "text/markdown"
conditions:
  - displayName: "Cloud SQL CPU > 90%"
    conditionThreshold:
      filter: |
        resource.type = "cloudsql_database"
        AND resource.labels.database_id = "mizzou-news-crawler:mizzou-db-prod"
        AND metric.type = "cloudsql.googleapis.com/database/cpu/utilization"
      aggregations:
        - alignmentPeriod: "300s"
          perSeriesAligner: "ALIGN_MEAN"
      comparison: "COMPARISON_GT"
      thresholdValue: 0.9
      duration: "300s"
combiner: "OR"
enabled: true
alertStrategy:
  autoClose: "1800s"
severity: "CRITICAL"
EOF

create_alert "cloudsql-cpu" "/tmp/alert-cloudsql-cpu.yaml"

# Critical Alert: Cloud SQL Memory High
cat > /tmp/alert-cloudsql-memory.yaml <<'EOF'
displayName: "CRITICAL: Cloud SQL Memory > 95%"
documentation:
  content: "Cloud SQL memory utilization > 95%. Immediate action required."
  mimeType: "text/markdown"
conditions:
  - displayName: "Cloud SQL Memory > 95%"
    conditionThreshold:
      filter: |
        resource.type = "cloudsql_database"
        AND resource.labels.database_id = "mizzou-news-crawler:mizzou-db-prod"
        AND metric.type = "cloudsql.googleapis.com/database/memory/utilization"
      aggregations:
        - alignmentPeriod: "300s"
          perSeriesAligner: "ALIGN_MEAN"
      comparison: "COMPARISON_GT"
      thresholdValue: 0.95
      duration: "300s"
combiner: "OR"
enabled: true
alertStrategy:
  autoClose: "1800s"
severity: "CRITICAL"
EOF

create_alert "cloudsql-memory" "/tmp/alert-cloudsql-memory.yaml"

# Warning Alert: Container Memory High
cat > /tmp/alert-container-memory.yaml <<'EOF'
displayName: "WARNING: Container Memory > 80%"
documentation:
  content: "Container memory usage > 80%. Monitor for OOMKills."
  mimeType: "text/markdown"
conditions:
  - displayName: "Container Memory > 80%"
    conditionThreshold:
      filter: |
        resource.type = "k8s_container"
        AND resource.labels.cluster_name = "mizzou-cluster"
        AND resource.labels.namespace_name = "production"
        AND metric.type = "kubernetes.io/container/memory/limit_utilization"
      aggregations:
        - alignmentPeriod: "300s"
          perSeriesAligner: "ALIGN_MEAN"
          crossSeriesReducer: "REDUCE_MEAN"
          groupByFields:
            - "resource.pod_name"
      comparison: "COMPARISON_GT"
      thresholdValue: 0.8
      duration: "600s"
combiner: "OR"
enabled: true
alertStrategy:
  autoClose: "3600s"
severity: "WARNING"
EOF

create_alert "container-memory" "/tmp/alert-container-memory.yaml"

# Warning Alert: Error Log Rate
cat > /tmp/alert-error-logs.yaml <<'EOF'
displayName: "WARNING: High Error Log Rate"
documentation:
  content: "Error log rate > 10 errors/minute. Check application logs."
  mimeType: "text/markdown"
conditions:
  - displayName: "Error logs > 10/min"
    conditionThreshold:
      filter: |
        resource.type = "k8s_pod"
        AND resource.labels.cluster_name = "mizzou-cluster"
        AND resource.labels.namespace_name = "production"
        AND severity >= "ERROR"
      aggregations:
        - alignmentPeriod: "60s"
          perSeriesAligner: "ALIGN_RATE"
          crossSeriesReducer: "REDUCE_SUM"
      comparison: "COMPARISON_GT"
      thresholdValue: 10
      duration: "300s"
combiner: "OR"
enabled: true
alertStrategy:
  autoClose: "1800s"
severity: "WARNING"
EOF

create_alert "error-logs" "/tmp/alert-error-logs.yaml"

# Budget Alert (requires billing account setup)
echo "=== Budget Alert ==="
echo "To create budget alerts, run:"
echo ""
echo "gcloud billing budgets create \\"
echo "  --billing-account=BILLING_ACCOUNT_ID \\"
echo "  --display-name='MizzouNewsCrawler Monthly Budget' \\"
echo "  --budget-amount=200 \\"
echo "  --threshold-rule=percent=50 \\"
echo "  --threshold-rule=percent=90 \\"
echo "  --threshold-rule=percent=100"
echo ""

# Cleanup temp files
rm -f /tmp/alert-*.yaml

echo "=== Alert Policy Creation Complete ==="
echo ""
echo "View alert policies at:"
echo "https://console.cloud.google.com/monitoring/alerting/policies?project=$PROJECT_ID"
echo ""
echo "⚠️  Remember to verify the email notification channel!"
