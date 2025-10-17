# Cloud Monitoring Setup Guide

## Overview

This directory contains configurations and scripts for setting up Cloud Monitoring dashboards and alert policies for MizzouNewsCrawler.

## Components

### Dashboards

1. **system-health.json** - System infrastructure monitoring
   - GKE cluster CPU and memory utilization
   - Pod restart counts and running pod counts
   - Cloud SQL CPU and memory utilization
   - API request rates

2. **pipeline-metrics.json** - Data pipeline monitoring
   - Articles discovered and extracted counts
   - Pipeline success rates by stage
   - Argo workflow execution status
   - Processing time by stage
   - Error rates by component

### Alert Policies

Configured alerts include:

**Critical Alerts** (immediate notification):
- Pod restart rate > 3 in 10 minutes
- Cloud SQL CPU > 90%
- Cloud SQL Memory > 95%

**Warning Alerts** (investigate soon):
- Container memory usage > 80%
- Error log rate > 10 errors/minute

**Budget Alerts** (via separate billing setup):
- Monthly spend > 50% of $200 target
- Monthly spend > 90% of $200 target
- Monthly spend > 100% of $200 target

## Setup Instructions

### Prerequisites

1. **GCP Authentication**:
   ```bash
   gcloud auth login
   gcloud config set project mizzou-news-crawler
   ```

2. **Required APIs** (should already be enabled):
   - Cloud Monitoring API
   - Cloud Logging API
   - Kubernetes Engine API

### Step 1: Create Dashboards

```bash
cd monitoring
./create-dashboards.sh
```

This will create two dashboards in Cloud Monitoring. View them at:
https://console.cloud.google.com/monitoring/dashboards?project=mizzou-news-crawler

**Note**: Some metrics may not appear until:
- The application emits custom metrics (requires code instrumentation)
- Sufficient time has passed for metrics to accumulate

### Step 2: Create Alert Policies

```bash
cd monitoring
./create-alerts.sh
```

When prompted, enter the email address for alert notifications. You'll need to verify this email address via a link sent by Google.

View alert policies at:
https://console.cloud.google.com/monitoring/alerting/policies?project=mizzou-news-crawler

### Step 3: Configure Budget Alerts

Budget alerts require billing account access. Run:

```bash
# First, get your billing account ID
gcloud billing accounts list

# Create budget alert
gcloud billing budgets create \
  --billing-account=BILLING_ACCOUNT_ID \
  --display-name='MizzouNewsCrawler Monthly Budget' \
  --budget-amount=200 \
  --threshold-rule=percent=50 \
  --threshold-rule=percent=90 \
  --threshold-rule=percent=100 \
  --all-updates-rule-pubsub-topic=projects/mizzou-news-crawler/topics/budget-alerts
```

Or configure via UI:
https://console.cloud.google.com/billing/budgets

## Custom Metrics (Future Enhancement)

The dashboard and alert configurations reference custom metrics that need to be instrumented in the application code:

### Metrics to Implement

```python
# In your application code
from google.cloud import monitoring_v3
from google.api import metric_pb2 as ga_metric

client = monitoring_v3.MetricServiceClient()
project_name = f"projects/{project_id}"

# Example: Articles discovered metric
series = monitoring_v3.TimeSeries()
series.metric.type = "custom.googleapis.com/articles_discovered"
series.resource.type = "k8s_pod"
series.resource.labels["project_id"] = project_id
series.resource.labels["cluster_name"] = "mizzou-cluster"
series.resource.labels["namespace_name"] = "production"
series.resource.labels["pod_name"] = os.getenv("HOSTNAME")

point = monitoring_v3.Point()
point.value.int64_value = article_count
point.interval.end_time.GetCurrentTime()

series.points = [point]
client.create_time_series(name=project_name, time_series=[series])
```

### Recommended Custom Metrics

1. **articles_discovered** - Count of URLs discovered per run
2. **articles_extracted** - Count of articles successfully extracted
3. **pipeline_success_rate** - Success rate by stage (discovery, verification, extraction)
4. **processing_time_seconds** - Processing duration by stage
5. **workflow_executions** - Argo workflow run status
6. **api_requests** - API endpoint request counts

## Dashboard Customization

### Editing Dashboards

1. Via Cloud Console:
   - Navigate to the dashboard
   - Click "Edit" in the top-right
   - Add/modify widgets
   - Save changes

2. Via JSON (recommended for version control):
   - Edit the JSON file in `dashboards/`
   - Delete the old dashboard or get its ID
   - Re-run `./create-dashboards.sh`

### Common Customizations

**Add a new widget**:
```json
{
  "xPos": 0,
  "yPos": 16,
  "width": 6,
  "height": 4,
  "widget": {
    "title": "Your Custom Metric",
    "xyChart": {
      "dataSets": [{
        "timeSeriesQuery": {
          "timeSeriesFilter": {
            "filter": "metric.type=\"your.metric.type\"",
            "aggregation": {
              "alignmentPeriod": "60s",
              "perSeriesAligner": "ALIGN_RATE"
            }
          }
        },
        "plotType": "LINE"
      }]
    }
  }
}
```

**Add a threshold line**:
```json
"thresholds": [
  {
    "value": 0.8,
    "color": "YELLOW",
    "direction": "ABOVE"
  },
  {
    "value": 0.95,
    "color": "RED",
    "direction": "ABOVE"
  }
]
```

## Alert Policy Customization

### Modifying Alert Thresholds

Edit the YAML files in the `create-alerts.sh` script:

```yaml
thresholdValue: 0.9  # Change this value
duration: "300s"     # Change alert persistence time
```

### Adding New Alert Policies

Example alert for API latency:

```yaml
displayName: "WARNING: API Latency High"
documentation:
  content: "API p95 latency > 1 second"
  mimeType: "text/markdown"
conditions:
  - displayName: "API p95 latency > 1s"
    conditionThreshold:
      filter: |
        resource.type = "k8s_pod"
        AND metric.type = "custom.googleapis.com/api_latency_p95"
      aggregations:
        - alignmentPeriod: "300s"
          perSeriesAligner: "ALIGN_MEAN"
      comparison: "COMPARISON_GT"
      thresholdValue: 1000  # milliseconds
      duration: "600s"
combiner: "OR"
enabled: true
severity: "WARNING"
```

## Notification Channels

### Supported Channel Types

- **Email** - Individual or group email
- **Slack** - Webhook integration
- **PagerDuty** - For on-call alerts
- **SMS** - For critical alerts
- **Pub/Sub** - For custom integrations

### Adding Slack Notifications

```bash
# Create Slack webhook URL first in Slack workspace

gcloud alpha monitoring channels create \
  --display-name="Slack - MizzouNews" \
  --type=slack \
  --channel-labels=url=https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK
```

Then update alert policies to include the new channel.

## Troubleshooting

### Dashboards Show No Data

1. **Check metrics exist**:
   ```bash
   gcloud monitoring time-series list \
     --filter='metric.type="kubernetes.io/container/cpu/core_usage_time"' \
     --format=json \
     --limit=1
   ```

2. **Verify time range** - Adjust dashboard time selector

3. **Custom metrics not appearing** - Ensure application is emitting them

### Alerts Not Firing

1. **Verify notification channel**:
   ```bash
   gcloud alpha monitoring channels list
   ```

2. **Check channel is verified** (especially email)

3. **Test alert policy**:
   - Temporarily lower threshold to trigger alert
   - Check incident logs in Cloud Console

4. **Review alert history**:
   https://console.cloud.google.com/monitoring/alerting/incidents

### Permission Issues

Ensure your account or service account has:
- `monitoring.dashboards.create`
- `monitoring.alertPolicies.create`
- `monitoring.notificationChannels.create`

## Cost Considerations

**Cloud Monitoring costs**:
- First 150 MB of logs per month: Free
- First 150 MB of metrics per month: Free
- Alert notifications: Free (email, Slack)
- Paid metrics beyond free tier: ~$0.26 per MB

**Expected cost for this project**: $5-15/month (well within free tier initially)

## Best Practices

1. **Start with critical alerts** - Don't create alert fatigue
2. **Use proper severity levels** - CRITICAL for immediate action, WARNING for investigate
3. **Document alert responses** - Add runbooks to alert documentation
4. **Set auto-close windows** - Prevent stale alert notifications
5. **Test alerts regularly** - Verify notification delivery
6. **Review metrics weekly** - Adjust thresholds as needed

## Next Steps

1. ✅ Create dashboards (`./create-dashboards.sh`)
2. ✅ Create alert policies (`./create-alerts.sh`)
3. ⏳ Verify email notification channel
4. ⏳ Instrument custom metrics in application code
5. ⏳ Set up budget alerts (requires billing permissions)
6. ⏳ Add Slack notifications (optional)
7. ⏳ Create runbooks for alert responses

## Resources

- [Cloud Monitoring Documentation](https://cloud.google.com/monitoring/docs)
- [Dashboard Configuration Reference](https://cloud.google.com/monitoring/api/ref_v3/rest/v1/projects.dashboards)
- [Alert Policy Reference](https://cloud.google.com/monitoring/api/ref_v3/rest/v3/projects.alertPolicies)
- [MQL (Monitoring Query Language)](https://cloud.google.com/monitoring/mql)

---

**Last Updated**: October 17, 2025  
**Maintained By**: MizzouNewsCrawler DevOps Team
