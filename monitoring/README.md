# Cloud Monitoring Setup Guide

## Overview

This directory contains configurations and scripts for setting up Cloud Monitoring dashboards and alert policies for MizzouNewsCrawler.

## Quick Start

### 1. Prerequisites

```bash
# Authenticate with GCP
gcloud auth login
gcloud config set project mizzou-news-crawler

# Verify required APIs are enabled
gcloud services list --enabled | grep -E "(monitoring|logging)"
```

### 2. Create Dashboards

```bash
cd monitoring
./create-dashboards.sh
```

This creates three dashboards:
- **System Health** - Infrastructure monitoring (CPU, memory, pods, database)
- **Pipeline Metrics** - Data pipeline performance (articles, success rates, processing times)
- **Business Metrics** - Business-level metrics (articles by county, CIN labels, entity coverage)

View dashboards: https://console.cloud.google.com/monitoring/dashboards?project=mizzou-news-crawler

### 3. Create Alert Policies

```bash
cd monitoring
./create-alerts.sh
```

When prompted, enter your email address for alert notifications. **Important:** You must verify the email address via the link sent by Google.

This creates 10 alert policies:
- **Critical alerts**: API error rate, pod restarts, database issues, disk space
- **Warning alerts**: API latency, memory usage, crawler success rate, queue backlog

View alerts: https://console.cloud.google.com/monitoring/alerting/policies?project=mizzou-news-crawler

### 4. Set Up Budget Alerts (Optional)

```bash
# Get billing account ID
gcloud billing accounts list

# Create budget alert
gcloud billing budgets create \
  --billing-account=BILLING_ACCOUNT_ID \
  --display-name='MizzouNewsCrawler Monthly Budget' \
  --budget-amount=200 \
  --threshold-rule=percent=50 \
  --threshold-rule=percent=90 \
  --threshold-rule=percent=100
```

Or configure via UI: https://console.cloud.google.com/billing/budgets

## Application Integration

The application automatically emits structured logs and custom metrics when properly configured.

### Structured Logging

Logging is automatically configured in the API (`backend/app/main.py`) and can be added to CLI commands:

```python
from src.utils.logging_config import setup_logging, get_logger

# At application startup
setup_logging(level="INFO", service_name="crawler")

# In your code
logger = get_logger(__name__)
logger.info("article_discovered", url=url, source=source)
```

### Custom Metrics

Metrics are emitted using the metrics client:

```python
from src.utils.metrics import get_metrics_client

metrics = get_metrics_client()

# Record articles discovered
metrics.record_articles_discovered(count=42, source="example.com")

# Record processing time
metrics.record_processing_time(stage="extraction", duration_seconds=12.3)

# Record queue depth
metrics.record_queue_depth(queue_name="verification_pending", depth=1234)
```

### Example Integration

See `src/utils/observability_examples.py` for complete examples of integrating observability into:
- Discovery pipeline
- Extraction pipeline
- Processing commands
- Queue monitoring

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
   - Processing time by stage (p50, p95, p99)
   - Queue depths
   - Error rates by component

3. **business-metrics.json** - Business-level monitoring
   - Articles by county
   - Articles by source
   - CIN label distribution
   - Entity extraction coverage
   - Article freshness
   - Content quality scores

### Alert Policies

**Critical Alerts** (immediate notification):
- Pod restart rate > 3 in 10 minutes
- API error rate > 5%
- Cloud SQL CPU > 90%
- Cloud SQL Memory > 95%
- Disk usage > 90%

**Warning Alerts** (investigate soon):
- Container memory usage > 80%
- API latency p95 > 1 second
- Crawler success rate < 90%
- Queue depth > 1000 for 30 minutes
- Error log rate > 10 errors/minute

**Budget Alerts** (via separate billing setup):
- Monthly spend > 50% of $200 target
- Monthly spend > 90% of $200 target
- Monthly spend > 100% of $200 target

## Customization

### Editing Dashboards

#### Via Cloud Console (Easy)

1. Navigate to the dashboard
2. Click "Edit" in the top-right
3. Add/modify widgets using the visual editor
4. Save changes

#### Via JSON (Version Control - Recommended)

1. Edit the JSON file in `dashboards/`
2. Delete the old dashboard or get its ID:
   ```bash
   gcloud monitoring dashboards list --format="table(name,displayName)"
   ```
3. Re-run `./create-dashboards.sh` or create manually:
   ```bash
   gcloud monitoring dashboards create \
     --config-from-file=dashboards/system-health.json
   ```

### Modifying Alert Thresholds

Edit the alert YAML in `create-alerts.sh`:

```yaml
thresholdValue: 0.9  # Change threshold
duration: "300s"     # Change alert persistence time
```

Then re-run `./create-alerts.sh`.

### Adding New Metrics

1. Define metric in your code:
   ```python
   metrics.record_gauge("my_custom_metric", value, labels={"key": "value"})
   ```

2. Add to dashboard JSON:
   ```json
   {
     "filter": "metric.type=\"custom.googleapis.com/my_custom_metric\"",
     "aggregation": {
       "alignmentPeriod": "60s",
       "perSeriesAligner": "ALIGN_MEAN"
     }
   }
   ```

3. Optionally create alert policy for the metric

## Troubleshooting

### Dashboards Show No Data

1. **Check metrics exist**:
   ```bash
   gcloud monitoring time-series list \
     --filter='metric.type="kubernetes.io/container/cpu/core_usage_time"' \
     --format=json --limit=1
   ```

2. **Adjust time range** - Try different time windows in the dashboard

3. **Wait for data** - New metrics take 1-2 minutes to appear

### Alerts Not Firing

1. **Verify notification channel**:
   ```bash
   gcloud alpha monitoring channels list
   ```

2. **Check verification status** - Email must be verified

3. **Test alert policy** - Temporarily lower threshold to trigger

4. **Review alert history**:
   https://console.cloud.google.com/monitoring/alerting/incidents

### Custom Metrics Not Appearing

1. **Check application logs** for metric emission:
   ```bash
   kubectl logs -n production -l app=api | grep "Recorded metric"
   ```

2. **Verify Cloud Monitoring client initialization**:
   ```bash
   kubectl logs -n production -l app=api | grep "metrics"
   ```

3. **Check for authentication errors**

4. **Ensure `DISABLE_METRICS` environment variable is not set**

## Cost Considerations

**Cloud Monitoring costs**:
- First 150 MB of logs per month: Free
- First 150 MB of metrics per month: Free
- Alert notifications (email, Slack): Free
- Paid metrics beyond free tier: ~$0.26 per MB

**Expected cost for MizzouNewsCrawler**: $5-15/month (within free tier initially)

### Optimization Tips

1. **Sample metrics** - Don't emit every single event
2. **Use appropriate log levels** - INFO in production, DEBUG only when troubleshooting
3. **Set retention policies** - 30 days for logs (not forever)
4. **Use log exclusion filters** for noisy logs

## Documentation

For comprehensive documentation, see:
- **[docs/OBSERVABILITY_GUIDE.md](../docs/OBSERVABILITY_GUIDE.md)** - Complete observability guide with:
  - Architecture overview
  - Structured logging usage
  - Custom metrics API
  - Dashboard management
  - Alert runbooks
  - Testing procedures
  - Best practices

## Support

For issues or questions:
1. Check the [OBSERVABILITY_GUIDE.md](../docs/OBSERVABILITY_GUIDE.md)
2. Review Cloud Monitoring [documentation](https://cloud.google.com/monitoring/docs)
3. Open an issue in the repository

---

**Last Updated**: November 22, 2025  
**Maintained By**: MizzouNewsCrawler DevOps Team
