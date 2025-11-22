# Observability Guide

## Overview

This guide describes the comprehensive observability and monitoring infrastructure for MizzouNewsCrawler in production. The system provides full visibility into:

- **System Health**: Infrastructure metrics (CPU, memory, pods, database)
- **Pipeline Metrics**: Articles discovered, extracted, processing times
- **Business Metrics**: Articles by county, CIN labels, entity extraction
- **Alerts**: Critical and warning conditions with automatic notifications
- **Structured Logging**: JSON logs with trace correlation

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────────┐
│                  Google Cloud Monitoring                     │
│  ┌────────────┐  ┌────────────┐  ┌─────────────┐           │
│  │ Dashboards │  │   Alerts   │  │  Log Query  │           │
│  └────────────┘  └────────────┘  └─────────────┘           │
└─────────────────────────────────────────────────────────────┘
         ▲                 ▲                ▲
         │                 │                │
    Metrics           Alerts           Logs
         │                 │                │
┌────────┴─────────────────┴────────────────┴────────────────┐
│                  Kubernetes (GKE)                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │   API    │  │ Crawler  │  │Processor │  │  Argo    │   │
│  │  Pods    │  │  Pods    │  │  Pods    │  │Workflows │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
│       │              │              │             │         │
│    structlog    structlog      structlog     structlog      │
│    metrics      metrics        metrics       metrics        │
└─────────────────────────────────────────────────────────────┘
```

### Monitoring Stack

- **Metrics**: Google Cloud Monitoring (custom metrics + system metrics)
- **Logs**: Cloud Logging with structured JSON output
- **Dashboards**: Cloud Monitoring dashboards
- **Alerts**: Cloud Monitoring alert policies
- **Notifications**: Email, Slack, PagerDuty (configurable)

## Structured Logging

### Configuration

The application uses `structlog` for structured JSON logging in production:

```python
from src.utils.logging_config import setup_logging, get_logger

# Initialize at application startup
setup_logging(
    level="INFO",
    service_name="api"  # or "crawler", "processor"
)

# Get logger in your module
logger = get_logger(__name__)
```

### Log Formats

**Production (JSON)**:
```json
{
  "event": "article_extracted",
  "article_id": 12345,
  "source": "example.com",
  "county": "Boone",
  "extraction_time_ms": 1234.5,
  "timestamp": "2025-11-22T19:00:00.123Z",
  "level": "info",
  "logger": "src.pipeline.extraction"
}
```

**Local Development (Console)**:
```
2025-11-22 19:00:00 [info     ] article_extracted       article_id=12345 source=example.com
```

### Trace Correlation

Bind trace IDs to correlate logs across services:

```python
from src.utils.logging_config import bind_trace_context, get_logger

logger = get_logger(__name__)

# Bind trace context at request start
bind_trace_context(trace_id="abc123", span_id="def456")

# All subsequent logs will include trace_id and span_id
logger.info("processing_request", user_id=123)

# Clear context when done
unbind_trace_context()
```

### Request Context

For API requests, bind request context:

```python
from src.utils.logging_config import bind_request_context

bind_request_context(
    request_id="req-123",
    user_id="user-456",
    endpoint="/api/articles"
)
```

### Querying Logs

**Cloud Logging Query Language**:

```
# Find all errors in the last hour
resource.type="k8s_pod"
resource.labels.cluster_name="mizzou-cluster"
severity>=ERROR
timestamp>="2025-11-22T18:00:00Z"

# Find logs for a specific trace
resource.type="k8s_pod"
jsonPayload.trace_id="abc123"

# Find extraction failures
resource.type="k8s_pod"
jsonPayload.event="extraction_failed"
jsonPayload.source="example.com"
```

## Custom Metrics

### Metrics Client

Initialize the metrics client:

```python
from src.utils.metrics import get_metrics_client

# Get global metrics client (auto-initialized)
metrics = get_metrics_client()

# Disable in tests/local dev
metrics = get_metrics_client(enabled=False)
```

### Available Metrics

#### 1. Articles Discovered

```python
metrics.record_articles_discovered(
    count=42,
    source="example.com"
)
```

Metric: `custom.googleapis.com/articles_discovered`  
Type: Counter  
Labels: `source` (optional)

#### 2. Articles Extracted

```python
metrics.record_articles_extracted(
    count=38,
    source="example.com",
    success=True
)
```

Metric: `custom.googleapis.com/articles_extracted`  
Type: Counter  
Labels: `source` (optional), `success` (true/false)

#### 3. Pipeline Success Rate

```python
metrics.record_pipeline_success_rate(
    stage="extraction",
    success_rate=0.95  # 95%
)
```

Metric: `custom.googleapis.com/pipeline_success_rate`  
Type: Gauge (0.0 to 1.0)  
Labels: `stage` (discovery, extraction, analysis)

#### 4. Processing Time

```python
import time
start = time.time()
# ... do work ...
duration = time.time() - start

metrics.record_processing_time(
    stage="extraction",
    duration_seconds=duration
)
```

Metric: `custom.googleapis.com/processing_time_seconds`  
Type: Distribution (supports percentiles)  
Labels: `stage` (discovery, extraction, analysis)

#### 5. Queue Depth

```python
metrics.record_queue_depth(
    queue_name="verification_pending",
    depth=1234
)
```

Metric: `custom.googleapis.com/queue_depth`  
Type: Gauge  
Labels: `queue` (verification_pending, extraction_pending, etc.)

### Using Metrics in Code

**Example: Discovery Pipeline**

```python
from src.utils.metrics import get_metrics_client
from src.utils.logging_config import get_logger
import time

logger = get_logger(__name__)
metrics = get_metrics_client()

def discover_articles(source: str):
    start = time.time()
    
    try:
        # Discover articles
        articles = fetch_articles(source)
        
        # Record success
        metrics.record_articles_discovered(
            count=len(articles),
            source=source
        )
        
        duration = time.time() - start
        metrics.record_processing_time(
            stage="discovery",
            duration_seconds=duration
        )
        
        logger.info(
            "discovery_complete",
            source=source,
            count=len(articles),
            duration_seconds=duration
        )
        
        return articles
        
    except Exception as e:
        logger.error(
            "discovery_failed",
            source=source,
            error=str(e),
            exc_info=True
        )
        raise
```

## Dashboards

### Available Dashboards

#### 1. System Health Dashboard

**Purpose**: Monitor infrastructure health and resource utilization

**Widgets**:
- GKE Cluster CPU Utilization (by pod)
- GKE Cluster Memory Utilization (by pod)
- Pod Restart Count
- Running Pods Count
- Cloud SQL CPU Utilization
- Cloud SQL Memory Usage
- API Request Rate

**Access**: [Cloud Console - System Health](https://console.cloud.google.com/monitoring/dashboards?project=mizzou-news-crawler)

#### 2. Pipeline Metrics Dashboard

**Purpose**: Monitor data pipeline performance and throughput

**Widgets**:
- Articles Discovered (count over time)
- Articles Extracted (count over time)
- Extraction Success Rate
- Processing Time by Stage (p50, p95, p99)
- Queue Depth by Queue
- Error Rate by Component

**Access**: [Cloud Console - Pipeline Metrics](https://console.cloud.google.com/monitoring/dashboards?project=mizzou-news-crawler)

#### 3. Business Metrics Dashboard

**Purpose**: Monitor business-level metrics and data quality

**Widgets**:
- Articles by County
- Articles by Source
- CIN Label Distribution
- Entity Extraction Coverage
- Article Freshness
- Content Quality Score

**Note**: This dashboard requires custom queries on the production database. See [Creating Business Dashboards](#creating-business-dashboards) below.

### Creating and Updating Dashboards

#### Via Script (Recommended)

```bash
cd monitoring
./create-dashboards.sh
```

This creates/updates:
- `system-health` dashboard
- `pipeline-metrics` dashboard

#### Via Cloud Console

1. Navigate to [Cloud Monitoring Dashboards](https://console.cloud.google.com/monitoring/dashboards?project=mizzou-news-crawler)
2. Click "Create Dashboard"
3. Add widgets using the visual editor
4. Save changes

#### Via JSON (Version Control)

Edit dashboard JSON files in `monitoring/dashboards/`:
- `system-health.json`
- `pipeline-metrics.json`

Then apply:
```bash
gcloud monitoring dashboards create \
  --config-from-file=monitoring/dashboards/system-health.json
```

### Dashboard Best Practices

1. **Use appropriate time windows**: Default to 1 hour for operations, 24 hours for trends
2. **Add threshold lines**: Highlight critical values (e.g., 80% memory usage)
3. **Group related metrics**: CPU/memory together, queue depths together
4. **Use consistent colors**: Red for errors, yellow for warnings, green for success
5. **Include percentiles**: p50, p95, p99 for latency metrics

## Alerts

### Alert Categories

#### Critical Alerts (Immediate Action Required)

**1. API Error Rate > 5%**
- **Condition**: Error rate exceeds 5% for 5 minutes
- **Notification**: Immediate (email, PagerDuty)
- **Severity**: CRITICAL
- **Runbook**: [API Error Rate Alert](#api-error-rate-alert)

**2. Pod Restart Count > 3**
- **Condition**: Pod restarts more than 3 times in 10 minutes
- **Notification**: Immediate
- **Severity**: CRITICAL
- **Runbook**: [Pod Restart Alert](#pod-restart-alert)

**3. Database Connection Failure**
- **Condition**: Cloud SQL CPU > 90% or connection failures
- **Notification**: Immediate
- **Severity**: CRITICAL
- **Runbook**: [Database Alert](#database-alert)

**4. Disk Usage > 90%**
- **Condition**: Persistent volume disk usage > 90%
- **Notification**: Immediate
- **Severity**: CRITICAL
- **Runbook**: [Disk Space Alert](#disk-space-alert)

#### Warning Alerts (Investigate Soon)

**1. High API Latency**
- **Condition**: API p95 latency > 1 second for 10 minutes
- **Notification**: Email
- **Severity**: WARNING
- **Runbook**: [API Latency Alert](#api-latency-alert)

**2. High Memory Usage**
- **Condition**: Container memory > 80% for 15 minutes
- **Notification**: Email
- **Severity**: WARNING
- **Runbook**: [Memory Alert](#memory-alert)

**3. Low Crawler Success Rate**
- **Condition**: Crawler success rate < 90% for 30 minutes
- **Notification**: Email
- **Severity**: WARNING
- **Runbook**: [Crawler Alert](#crawler-alert)

**4. Queue Backlog**
- **Condition**: Queue depth > 1000 for 30 minutes
- **Notification**: Email
- **Severity**: WARNING
- **Runbook**: [Queue Backlog Alert](#queue-backlog-alert)

#### Budget Alerts

**1. Monthly Spend > 90%**
- **Condition**: Monthly spend exceeds $180 (90% of $200 target)
- **Notification**: Email to billing admins
- **Severity**: WARNING

**2. Daily Spend > $10**
- **Condition**: Daily spend exceeds $10 (extrapolates to > $300/month)
- **Notification**: Email to billing admins
- **Severity**: WARNING

### Creating Alerts

#### Via Script

```bash
cd monitoring
./create-alerts.sh
```

When prompted, enter email address for notifications.

**Note**: Email addresses must be verified before alerts will be sent.

#### Via Cloud Console

1. Navigate to [Alerting Policies](https://console.cloud.google.com/monitoring/alerting/policies?project=mizzou-news-crawler)
2. Click "Create Policy"
3. Configure condition, notification, and documentation
4. Save policy

### Alert Runbooks

#### API Error Rate Alert

**Symptoms**:
- High 4xx/5xx error rate
- Failed requests in logs

**Diagnosis**:
```bash
# Check recent errors
gcloud logging read \
  'resource.type="k8s_pod" severity>=ERROR timestamp>="2025-11-22T18:00:00Z"' \
  --limit 50 --format json | jq

# Check API pod status
kubectl get pods -n production -l app=api

# Check API logs
kubectl logs -n production -l app=api --tail=100
```

**Resolution**:
1. Check if error is from a specific endpoint or source
2. Review recent deployments (possible regression)
3. Check database connectivity
4. Check external service dependencies
5. Scale API pods if needed: `kubectl scale deployment api -n production --replicas=3`

#### Pod Restart Alert

**Symptoms**:
- Pods restarting frequently
- CrashLoopBackOff status

**Diagnosis**:
```bash
# Check pod status
kubectl get pods -n production

# Describe pod for events
kubectl describe pod <pod-name> -n production

# Check pod logs
kubectl logs <pod-name> -n production --previous
```

**Resolution**:
1. Check for OOM kills (memory limit too low)
2. Check for liveness probe failures
3. Review recent code changes
4. Check for resource contention
5. Rollback deployment if needed: `kubectl rollout undo deployment/<name> -n production`

#### Database Alert

**Symptoms**:
- Connection timeouts
- High CPU/memory on Cloud SQL
- Slow queries

**Diagnosis**:
```bash
# Check Cloud SQL metrics
gcloud sql instances describe mizzou-news-db

# Check active connections
gcloud sql operations list --instance=mizzou-news-db --limit=10

# Run query analysis (from pod)
kubectl exec -it <api-pod> -n production -- \
  python -c "from src.models.database import DatabaseManager; db = DatabaseManager(); \
  with db.get_session() as s: \
    result = s.execute('SELECT * FROM pg_stat_activity'); \
    print(result.fetchall())"
```

**Resolution**:
1. Check for long-running queries
2. Kill problematic queries if safe
3. Scale up Cloud SQL instance if needed
4. Check connection pool settings
5. Analyze slow query log

#### Disk Space Alert

**Symptoms**:
- PV near capacity
- Pod unable to write logs

**Diagnosis**:
```bash
# Check PVC usage
kubectl get pvc -n production

# Check disk usage from pod
kubectl exec -it <pod-name> -n production -- df -h
```

**Resolution**:
1. Identify large files: `kubectl exec <pod> -- du -sh /* | sort -h`
2. Clean up old logs/temp files
3. Resize PVC if needed
4. Archive old data to Cloud Storage

#### API Latency Alert

**Symptoms**:
- Slow API responses
- High p95/p99 latency

**Diagnosis**:
```bash
# Check API metrics in dashboard
# Look for:
# - Slow database queries
# - External API timeouts
# - CPU throttling

# Check slow queries
kubectl exec -it <api-pod> -n production -- \
  tail -f /var/log/api.log | grep "duration_ms"
```

**Resolution**:
1. Identify slow endpoints from metrics
2. Check database query performance
3. Add caching if appropriate
4. Scale API pods if CPU-bound
5. Optimize slow code paths

#### Memory Alert

**Symptoms**:
- High memory usage
- Approaching OOM

**Diagnosis**:
```bash
# Check memory usage by pod
kubectl top pods -n production

# Check memory limits
kubectl describe pod <pod-name> -n production | grep -A 5 Limits
```

**Resolution**:
1. Check for memory leaks
2. Increase memory limits if legitimate growth
3. Add memory profiling to identify leaks
4. Restart pod if temporary spike
5. Scale horizontally instead of vertically

#### Crawler Alert

**Symptoms**:
- Low success rate for article discovery/extraction
- Many failed requests

**Diagnosis**:
```bash
# Check crawler logs
kubectl logs -n production -l app=crawler --tail=100

# Check HTTP error telemetry
curl https://api.example.com/api/telemetry/http-errors

# Check verification telemetry
curl https://api.example.com/api/telemetry/verification-stats
```

**Resolution**:
1. Check if failures are source-specific
2. Verify source sites are accessible
3. Check for bot detection/blocking
4. Update selectors if site changed
5. Add retry logic or backoff

#### Queue Backlog Alert

**Symptoms**:
- Queue depth growing
- Processing falling behind

**Diagnosis**:
```bash
# Check queue status
curl https://api.example.com/api/telemetry/operations/queue-status

# Check processor status
kubectl get pods -n production -l app=processor

# Check Argo workflows
kubectl get workflows -n argo
```

**Resolution**:
1. Scale up processor pods
2. Check for stuck workflows
3. Check for processor errors
4. Increase processing parallelism
5. Temporarily pause discovery if needed

### Notification Channels

#### Email

Created automatically by `create-alerts.sh`. Email must be verified.

**Verification**:
```bash
gcloud alpha monitoring channels list \
  --filter="type=email" \
  --format="table(name,labels.email_address,verificationStatus)"
```

#### Slack

```bash
# Create Slack webhook in your workspace first
# Then create notification channel:

gcloud alpha monitoring channels create \
  --display-name="Slack - MizzouNews" \
  --type=slack \
  --channel-labels=url=https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK
```

#### PagerDuty

```bash
# Get PagerDuty integration key first
# Then create notification channel:

gcloud alpha monitoring channels create \
  --display-name="PagerDuty - MizzouNews" \
  --type=pagerduty \
  --channel-labels=service_key=YOUR_PAGERDUTY_KEY
```

## Health Checks

### Endpoints

#### `/health`

**Purpose**: Basic liveness check

**Response**:
```json
{
  "status": "healthy",
  "service": "api"
}
```

**Status Codes**:
- 200: Service is alive
- 503: Service is down

**Kubernetes Configuration**:
```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 30
  periodSeconds: 10
```

#### `/ready`

**Purpose**: Readiness check (can serve traffic)

**Response**:
```json
{
  "status": "ready",
  "checks": {
    "database": "available",
    "telemetry": "available"
  },
  "message": "All systems operational"
}
```

**Status Codes**:
- 200: Service is ready
- 503: Service not ready (startup incomplete, DB unavailable)

**Kubernetes Configuration**:
```yaml
readinessProbe:
  httpGet:
    path: /ready
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 5
```

## Testing Observability

### Local Testing

#### 1. Test Structured Logging

```python
# test_logging.py
from src.utils.logging_config import setup_logging, get_logger

setup_logging(level="INFO", force_json=True)
logger = get_logger(__name__)

logger.info("test_event", user_id=123, action="login")
# Should output JSON:
# {"event": "test_event", "user_id": 123, "action": "login", ...}
```

#### 2. Test Metrics (Dry Run)

```python
from src.utils.metrics import get_metrics_client

# Disable actual emission
metrics = get_metrics_client(enabled=False)

# Metrics will log but not send to Cloud Monitoring
metrics.record_articles_discovered(count=10, source="test.com")
```

#### 3. Test Health Endpoints

```bash
# Start API locally
uvicorn backend.app.main:app --reload

# Test health
curl http://localhost:8000/health

# Test readiness
curl http://localhost:8000/ready
```

### Production Verification

#### 1. Verify Metrics Flow

```bash
# Check if custom metrics exist
gcloud monitoring time-series list \
  --filter='metric.type="custom.googleapis.com/articles_discovered"' \
  --format=json \
  --limit=1

# Should return recent data points
```

#### 2. Verify Dashboards

1. Navigate to [Cloud Monitoring Dashboards](https://console.cloud.google.com/monitoring/dashboards?project=mizzou-news-crawler)
2. Open "System Health" dashboard
3. Verify widgets show data (may take 1-2 minutes for new metrics)

#### 3. Verify Alerts

```bash
# List alert policies
gcloud alpha monitoring policies list \
  --format="table(displayName,enabled,conditions)"

# Verify notification channels
gcloud alpha monitoring channels list \
  --format="table(displayName,type,labels)"
```

#### 4. Test Alert Firing

**Temporarily lower threshold**:
```bash
# Edit alert policy to trigger easily
# Wait for alert to fire
# Check notification received
# Restore original threshold
```

#### 5. Verify Structured Logs

```bash
# Query recent logs
gcloud logging read \
  'resource.type="k8s_pod" jsonPayload.event!=""' \
  --limit 10 \
  --format json | jq '.[] | {event: .jsonPayload.event, timestamp: .timestamp}'
```

## Cost Considerations

### Cloud Monitoring Costs

**Free Tier**:
- First 150 MB of logs: Free
- First 150 MB of metrics: Free
- Alert notifications (email, Slack): Free

**Paid Usage**:
- Logs: $0.50 per GB ingested
- Metrics: ~$0.26 per MB beyond free tier
- Traces: $0.20 per million spans

**Expected Cost for MizzouNewsCrawler**: $5-15/month (within free tier initially)

### Optimization Tips

1. **Sample metrics**: Don't emit every single event, batch or sample
2. **Log levels**: Use INFO in production, DEBUG only when troubleshooting
3. **Retention**: Set log retention to 30 days (not forever)
4. **Filters**: Use log exclusion filters for noisy logs

```bash
# Example: Exclude health check logs
gcloud logging sinks create exclude-health-checks \
  --log-filter='jsonPayload.endpoint="/health"' \
  --destination='excluded-logs'
```

## Best Practices

### Logging Best Practices

1. **Use structured logging**: Always use structlog, not print()
2. **Include context**: Add relevant IDs (article_id, source, user_id)
3. **Log at appropriate levels**:
   - DEBUG: Detailed diagnostic info
   - INFO: Important events (article extracted)
   - WARNING: Unexpected but handled (retry succeeded)
   - ERROR: Errors that need attention
   - CRITICAL: System-level failures
4. **Don't log sensitive data**: No passwords, tokens, PII
5. **Use trace IDs**: Bind trace context for distributed tracing

### Metrics Best Practices

1. **Use appropriate metric types**:
   - Counter: Cumulative values (articles_discovered)
   - Gauge: Point-in-time values (queue_depth)
   - Distribution: Values for percentiles (latency)
2. **Add meaningful labels**: Source, stage, status
3. **Don't over-label**: Too many labels = high cardinality = cost
4. **Batch operations**: Emit metrics in batches when possible
5. **Use standard names**: Follow naming conventions

### Dashboard Best Practices

1. **Start simple**: Add widgets as needed, don't over-engineer
2. **Focus on actionable metrics**: What helps you make decisions?
3. **Use time comparisons**: Compare to last hour/day/week
4. **Add threshold lines**: Visual indicators of normal ranges
5. **Document widgets**: Add descriptions so others understand

### Alert Best Practices

1. **Avoid alert fatigue**: Only alert on actionable conditions
2. **Use appropriate severity**: CRITICAL = wake up, WARNING = check tomorrow
3. **Set correct thresholds**: Based on historical data, not guesses
4. **Write runbooks**: Every alert needs a runbook
5. **Test alerts**: Verify notifications are received
6. **Review regularly**: Adjust thresholds as system evolves

## Troubleshooting

### Metrics Not Appearing

**Problem**: Custom metrics not showing in dashboard

**Diagnosis**:
```bash
# Check if metrics are being sent
kubectl logs -n production -l app=api | grep "Recorded metric"

# Check Cloud Monitoring ingestion
gcloud monitoring time-series list \
  --filter='metric.type=~"custom.googleapis.com/.*"' \
  --format="table(metric.type)"
```

**Solutions**:
1. Verify `google-cloud-monitoring` library is installed
2. Check GCP credentials are available
3. Verify metrics client is enabled (`DISABLE_METRICS` not set)
4. Check for errors in logs
5. Wait 1-2 minutes for metrics to appear

### Logs Not in JSON Format

**Problem**: Logs are plain text, not structured JSON

**Diagnosis**:
```bash
# Check environment
kubectl exec -it <pod> -n production -- env | grep KUBERNETES

# Check logging setup
kubectl logs <pod> -n production | head -5
```

**Solutions**:
1. Verify `structlog` is installed
2. Check `setup_logging()` is called at startup
3. Verify running in Kubernetes (not local dev mode)
4. Check `force_json` parameter if needed

### Alerts Not Firing

**Problem**: Alert conditions met but no notification

**Diagnosis**:
```bash
# Check alert policy status
gcloud alpha monitoring policies list \
  --filter="displayName='Your Alert'" \
  --format=json

# Check notification channel
gcloud alpha monitoring channels list \
  --filter="displayName='Your Channel'" \
  --format=json | jq '.[] | {name, enabled, verificationStatus}'
```

**Solutions**:
1. Verify email address is verified
2. Check alert policy is enabled
3. Verify notification channel is attached to policy
4. Check alert history for incidents
5. Temporarily lower threshold to test

### Dashboard Shows No Data

**Problem**: Dashboard widgets are empty

**Solutions**:
1. Adjust time range (try last 1 hour, then 24 hours)
2. Verify metric filter is correct
3. Check if resources exist (pods running, metrics emitted)
4. Verify project ID in dashboard JSON
5. Check namespace and cluster names match

## Resources

### Documentation

- [Cloud Monitoring Overview](https://cloud.google.com/monitoring/docs)
- [Cloud Logging Overview](https://cloud.google.com/logging/docs)
- [Dashboard Configuration](https://cloud.google.com/monitoring/api/ref_v3/rest/v1/projects.dashboards)
- [Alert Policy Configuration](https://cloud.google.com/monitoring/api/ref_v3/rest/v3/projects.alertPolicies)
- [MQL (Monitoring Query Language)](https://cloud.google.com/monitoring/mql)
- [structlog Documentation](https://www.structlog.org/)

### Internal Documentation

- [GCP Kubernetes Roadmap](GCP_KUBERNETES_ROADMAP.md) - Phase 8 details
- [Operations Telemetry](OPERATIONS_TELEMETRY.md) - Existing telemetry endpoints
- [Pipeline Monitoring](PIPELINE_MONITORING.md) - Pipeline-specific metrics

### Tools

- [Cloud Console - Monitoring](https://console.cloud.google.com/monitoring?project=mizzou-news-crawler)
- [Cloud Console - Logging](https://console.cloud.google.com/logs?project=mizzou-news-crawler)
- [Cloud Console - Alerting](https://console.cloud.google.com/monitoring/alerting?project=mizzou-news-crawler)

---

**Last Updated**: November 22, 2025  
**Maintained By**: MizzouNewsCrawler DevOps Team
