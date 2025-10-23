# Argo Workflows Log Correlation Guide

## Understanding Workflow Job Names

Argo Workflows generates job names using the following pattern:

```text
mizzou-news-pipeline-1761156000-extraction-step-3155092536
                     ↑           ↑               ↑
                     |           |               |
                     |           |               └─ Argo-generated hash (unique node ID)
                     |           └─────────────── Template/step name
                     └────────────────────────── Unix timestamp (scheduled run time)
```

### Name Components

- **`mizzou-news-pipeline`** - CronWorkflow name
- **`1761156000`** - Unix timestamp = `Oct 22, 2025 18:00:00 UTC` (scheduled run time)
- **`extraction-step`** - Template name from the workflow
- **`3155092536`** - Argo-generated hash for unique node identification

## Semantic Labels for Log Correlation

To make it easier to correlate jobs within the same workflow run, we've added semantic labels to all workflow templates:

### Available Labels

| Label | Purpose | Example Value |
|-------|---------|---------------|
| `stage` | Pipeline stage identifier | `discovery`, `verification`, `extraction`, `wait-candidates`, `wait-verified` |
| `workflow-name` | Full workflow instance name | `mizzou-news-pipeline-1761156000` |
| `workflow-uid` | Immutable workflow UUID | `0adb260d-d970-46e6-aa9c-cfbca77e0c85` |
| `dataset` | Dataset being processed | `mizzou-missouri-state` |
| `pipeline-type` | Type of pipeline run | `scheduled`, `manual` |

## Common Log Queries

### Find All Jobs in a Specific Workflow Run

Using the workflow name (includes timestamp):

```bash
# Get all pods from a specific workflow instance
kubectl get pods -n production -l workflow-name=mizzou-news-pipeline-1761156000

# Get logs from all steps in that workflow
kubectl logs -n production -l workflow-name=mizzou-news-pipeline-1761156000 --all-containers=true

# Follow logs for a specific workflow run
kubectl logs -n production -l workflow-name=mizzou-news-pipeline-1761156000 --all-containers=true -f
```

Using the immutable workflow UID (survives renames):

```bash
# More reliable - uses UUID instead of name
kubectl logs -n production -l workflow-uid=0adb260d-d970-46e6-aa9c-cfbca77e0c85 --all-containers=true
```

### Find Jobs by Pipeline Stage

```bash
# Get all discovery pods across all workflow runs
kubectl get pods -n production -l stage=discovery

# Get logs from all extraction jobs in last 6 hours
kubectl logs -n production -l stage=extraction --since=6h

# Get all verification pods that are currently running
kubectl get pods -n production -l stage=verification --field-selector=status.phase=Running

# Follow logs for all extraction jobs in real-time
kubectl logs -n production -l stage=extraction -f --all-containers=true
```

### Combine Labels for Precise Filtering

```bash
# Find extraction jobs from a specific workflow
kubectl logs -n production -l stage=extraction,workflow-name=mizzou-news-pipeline-1761156000

# Find all jobs for a specific dataset
kubectl get pods -n production -l dataset=mizzou-missouri-state

# Find scheduled pipeline runs (exclude manual runs)
kubectl get pods -n production -l pipeline-type=scheduled

# Get recent discovery jobs for Mizzou dataset
kubectl logs -n production -l stage=discovery,dataset=mizzou-missouri-state --since=24h
```

### Debug Workflow Failures

```bash
# Get the workflow status
kubectl get workflow mizzou-news-pipeline-1761156000 -n production

# Find failed pods in that workflow
kubectl get pods -n production -l workflow-name=mizzou-news-pipeline-1761156000 --field-selector=status.phase=Failed

# Get logs from failed extraction step
kubectl logs -n production -l workflow-name=mizzou-news-pipeline-1761156000,stage=extraction --tail=100

# Describe a specific pod to see why it failed
kubectl describe pod -n production -l workflow-name=mizzou-news-pipeline-1761156000,stage=extraction
```

## Converting Unix Timestamps to Human-Readable Format

When you see a timestamp like `1761156000` in a workflow name:

```bash
# Using Python
python3 -c "import datetime; print(datetime.datetime.fromtimestamp(1761156000, tz=datetime.timezone.utc))"
# Output: 2025-10-22 18:00:00+00:00

# Using date command (macOS/Linux)
date -r 1761156000 -u
# Output: Tue Oct 22 18:00:00 UTC 2025
```

## Monitoring Active Workflows

```bash
# List all active workflows
kubectl get workflows -n production --field-selector=status.phase=Running

# Watch workflows in real-time
kubectl get workflows -n production -w

# Get recent workflow history (last 10)
kubectl get workflows -n production --sort-by=.metadata.creationTimestamp | tail -10

# Check CronWorkflow status
kubectl get cronworkflows -n production
```

## Argo UI Access

For visual workflow tracking:

```bash
# Port-forward to Argo UI
kubectl port-forward -n argo svc/argo-server 2746:2746

# Or use the task (runs in background with nohup)
# See tasks.json: "Argo: Port Forward UI"
```

Then access: <http://localhost:2746>

## Best Practices

1. **Always include workflow-name or workflow-uid** when debugging a specific run
1. **Use stage labels** for broad queries across multiple runs
1. **Combine labels** to narrow down to specific scenarios
1. **Use --since flag** to limit log volume for recent issues
1. **Use -f flag** for real-time monitoring of active workflows
1. **Check workflow status first** before diving into pod logs

## Example Debugging Session

```bash
# 1. Find recent failed workflows
kubectl get workflows -n production --field-selector=status.phase=Failed --sort-by=.metadata.creationTimestamp | tail -5

# 2. Pick a workflow to investigate (e.g., mizzou-news-pipeline-1761156000)
kubectl get workflow mizzou-news-pipeline-1761156000 -n production -o yaml

# 3. Find which stage failed
kubectl get pods -n production -l workflow-name=mizzou-news-pipeline-1761156000 --field-selector=status.phase=Failed

# 4. Get logs from the failed stage
kubectl logs -n production -l workflow-name=mizzou-news-pipeline-1761156000,stage=extraction --tail=200

# 5. Describe the pod for more details
kubectl describe pod -n production -l workflow-name=mizzou-news-pipeline-1761156000,stage=extraction
```

## Cleanup

```bash
# Delete old completed workflows (Argo will handle this automatically based on successfulJobsHistoryLimit)
kubectl delete workflows -n production --field-selector=status.phase=Succeeded --dry-run=client

# Delete workflows older than 7 days
kubectl get workflows -n production -o json | \
  jq -r '.items[] | select(.metadata.creationTimestamp < (now - 604800 | strftime("%Y-%m-%dT%H:%M:%SZ"))) | .metadata.name' | \
  xargs -I {} kubectl delete workflow {} -n production
```
