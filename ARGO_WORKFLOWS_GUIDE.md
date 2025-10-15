# Argo Workflows Integration Guide

## Overview

This guide explains how to use Argo Workflows for pipeline orchestration in the Mizzou News Crawler project. Argo Workflows provides production-grade orchestration with DAG visualization, per-step retry logic, and comprehensive observability.

## Why Argo Workflows?

### Current Issues (Before Argo)
- ❌ **No automated extraction**: Only manual jobs run extraction
- ❌ **No verification automation**: Verification never runs automatically
- ❌ **Conflicting CronJobs**: Three separate CronJobs with unclear purposes
- ❌ **Poor visibility**: No way to see pipeline progress or debug failures
- ❌ **No retry logic**: Must re-run entire pipeline if any step fails
- ❌ **Resource conflicts**: Multiple jobs competing for same sources/proxies

### Benefits with Argo Workflows
- ✅ **DAG visualization**: See pipeline progress in real-time UI
- ✅ **Free**: Open source, runs on existing GKE cluster (~$9/mo)
- ✅ **Per-step retry**: Retry just failed steps, not entire pipeline
- ✅ **Kubernetes-native**: Uses existing Docker images
- ✅ **Production-ready**: Used by Google, Intuit, SAP, etc.
- ✅ **Metrics & logging**: Built-in observability

## Architecture

### Pipeline Flow

```
Discovery (5-10 min) → Verification (10-30 min) → Extraction (30-60 min)
          ↓                    ↓                         ↓
    candidate_links       candidate_links            articles
   (status=discovered)    (status=article)      (status=extracted)

Continuous Processor (24/7) handles: Cleaning → ML Analysis → Entity Extraction
```

### Workflow Structure

Each pipeline (Mizzou, Lehigh) is a CronWorkflow with:
1. **Discovery Step**: Find new article URLs
2. **Verification Step**: Verify URLs are valid articles (conditional on discovery success)
3. **Extraction Step**: Extract article content (conditional on verification success)

Each step has:
- Automatic retry logic (2 retries with exponential backoff)
- Resource limits (CPU, memory)
- Dataset-specific rate limiting
- Environment configuration (database, proxy, etc.)

## Installation

### Prerequisites

- kubectl configured with access to your GKE cluster
- Access to the `production` namespace
- Argo Workflows CLI (optional, for local testing)

### Step 1: Install Argo Workflows

Run the deployment script:

```bash
# From repository root
./scripts/deploy_argo_workflows.sh
```

Or manually:

```bash
# Create argo namespace
kubectl create namespace argo

# Install Argo Workflows
kubectl apply -n argo -f https://github.com/argoproj/argo-workflows/releases/download/v3.5.0/install.yaml

# Wait for deployment
kubectl wait --for=condition=available --timeout=300s -n argo deployment/workflow-controller
kubectl wait --for=condition=available --timeout=300s -n argo deployment/argo-server
```

### Step 2: Deploy RBAC and Workflows

```bash
# Deploy ServiceAccount, Role, and RoleBinding
kubectl apply -f k8s/argo/rbac.yaml

# Deploy Mizzou pipeline
kubectl apply -f k8s/argo/mizzou-pipeline-workflow.yaml

# Deploy Lehigh pipeline
kubectl apply -f k8s/argo/lehigh-pipeline-workflow.yaml
```

### Step 3: Verify Installation

```bash
# Check CronWorkflows
kubectl get cronworkflow -n production

# Check Argo components
kubectl get pods -n argo
```

## Usage

### Accessing the Argo UI

```bash
# Port forward to Argo server
kubectl -n argo port-forward svc/argo-server 2746:2746

# Open in browser
open https://localhost:2746
```

### Managing Workflows

#### List Workflows

```bash
# List all CronWorkflows
kubectl get cronworkflow -n production

# List workflow executions
kubectl get workflows -n production

# Watch workflow execution
kubectl get workflows -n production -w
```

#### Trigger Manual Run

```bash
# Trigger Mizzou pipeline manually
kubectl create -n production -f - <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  generateName: mizzou-news-pipeline-manual-
spec:
  workflowTemplateRef:
    name: mizzou-news-pipeline
EOF

# Or using argo CLI
argo submit --from cronwf/mizzou-news-pipeline -n production
```

#### View Logs

```bash
# View workflow logs
kubectl logs -n production -l workflows.argoproj.io/workflow=<workflow-name>

# View specific step logs
kubectl logs -n production -l workflows.argoproj.io/workflow=<workflow-name> -c <step-name>

# Follow logs in real-time
kubectl logs -n production -l workflows.argoproj.io/workflow=<workflow-name> -f
```

#### Suspend/Resume CronWorkflows

```bash
# Suspend Mizzou pipeline (stop scheduled runs)
kubectl patch cronworkflow mizzou-news-pipeline -n production -p '{"spec":{"suspend":true}}'

# Resume Mizzou pipeline
kubectl patch cronworkflow mizzou-news-pipeline -n production -p '{"spec":{"suspend":false}}'

# Check suspension status
kubectl get cronworkflow mizzou-news-pipeline -n production -o jsonpath='{.spec.suspend}'
```

#### Delete Workflows

```bash
# Delete a specific workflow execution
kubectl delete workflow <workflow-name> -n production

# Delete CronWorkflow (stops all future runs)
kubectl delete cronworkflow mizzou-news-pipeline -n production
```

## Configuration

### Schedule Configuration

Workflows run on a cron schedule:

- **Mizzou**: `0 */6 * * *` (Every 6 hours at :00 - 00:00, 06:00, 12:00, 18:00 UTC)
- **Lehigh**: `30 */6 * * *` (Every 6 hours at :30 - 00:30, 06:30, 12:30, 18:30 UTC)

To change schedule, edit the `spec.schedule` field in the workflow YAML.

### Rate Limiting

#### Mizzou (Moderate)
- Inter-request: 5-15 seconds
- Batch sleep: 30 seconds
- CAPTCHA backoff: 30 min - 2 hours

#### Lehigh (Aggressive - Penn State bot protection)
- Inter-request: 90-180 seconds (1.5-3 minutes)
- Batch sleep: 420 seconds (7 minutes)
- CAPTCHA backoff: 2-6 hours

### Resource Limits

Each step has resource requests and limits:

**Discovery:**
- Requests: 200m CPU, 2Gi memory
- Limits: 1000m CPU, 4Gi memory

**Verification:**
- Requests: 250m CPU, 1Gi memory
- Limits: 1000m CPU, 3Gi memory

**Extraction:**
- Requests: 250m CPU, 1Gi memory
- Limits: 1000m CPU, 3Gi memory

## Monitoring

### Workflow Status

```bash
# Get workflow status
kubectl get workflow <workflow-name> -n production -o yaml

# Get workflow events
kubectl describe workflow <workflow-name> -n production

# Get pod status for workflow
kubectl get pods -n production -l workflows.argoproj.io/workflow=<workflow-name>
```

### Metrics

Argo provides metrics in Prometheus format:

```bash
# Port forward to metrics endpoint
kubectl -n argo port-forward svc/workflow-controller-metrics 9090:9090

# Access metrics
curl http://localhost:9090/metrics
```

Key metrics:
- `argo_workflows_count`: Total workflows
- `argo_workflows_error_count`: Failed workflows
- `argo_workflows_running_count`: Currently running workflows

### Logs

View logs through Argo UI or kubectl:

```bash
# Get all logs for a workflow
kubectl logs -n production -l workflows.argoproj.io/workflow=<workflow-name> --all-containers

# Get logs for specific step
kubectl logs -n production <pod-name> -c <container-name>
```

## Troubleshooting

### Workflow Won't Start

**Check CronWorkflow is not suspended:**
```bash
kubectl get cronworkflow mizzou-news-pipeline -n production -o jsonpath='{.spec.suspend}'
```

**Check schedule:**
```bash
kubectl get cronworkflow mizzou-news-pipeline -n production -o jsonpath='{.spec.schedule}'
```

**Check last execution:**
```bash
kubectl get cronworkflow mizzou-news-pipeline -n production -o jsonpath='{.status.lastScheduledTime}'
```

### Workflow Fails

**View workflow status:**
```bash
kubectl get workflow <workflow-name> -n production -o yaml
```

**View pod events:**
```bash
kubectl describe pod <pod-name> -n production
```

**Check logs:**
```bash
kubectl logs <pod-name> -n production -c <step-name>
```

### Step Hangs

**Check pod status:**
```bash
kubectl get pods -n production -l workflows.argoproj.io/workflow=<workflow-name>
```

**Check resource usage:**
```bash
kubectl top pod <pod-name> -n production
```

**Force delete stuck pod:**
```bash
kubectl delete pod <pod-name> -n production --grace-period=0 --force
```

## Rollback

If you need to rollback to the old CronJob system:

### Option 1: Using Script

```bash
# Dry run to see what would be deleted
DRY_RUN=true ./scripts/rollback_argo_workflows.sh

# Execute rollback
./scripts/rollback_argo_workflows.sh
```

### Option 2: Manual Rollback

```bash
# 1. Suspend Argo CronWorkflows
kubectl patch cronworkflow mizzou-news-pipeline -n production -p '{"spec":{"suspend":true}}'
kubectl patch cronworkflow lehigh-news-pipeline -n production -p '{"spec":{"suspend":true}}'

# 2. Delete running workflows
kubectl delete workflows -n production --all

# 3. Delete CronWorkflows
kubectl delete cronworkflow mizzou-news-pipeline lehigh-news-pipeline -n production

# 4. Delete RBAC resources
kubectl delete -f k8s/argo/rbac.yaml

# 5. Re-enable old CronJobs (if they still exist and are suspended)
kubectl patch cronjob mizzou-discovery -n production -p '{"spec":{"suspend":false}}'
kubectl patch cronjob mizzou-processor -n production -p '{"spec":{"suspend":false}}'
kubectl patch cronjob mizzou-crawler -n production -p '{"spec":{"suspend":false}}'
```

## Testing

### Run Tests

```bash
# Run Argo workflow tests
pytest tests/test_argo_workflows.py -v

# Run specific test
pytest tests/test_argo_workflows.py::test_workflow_yaml_is_valid -v
```

### Dry Run Deployment

```bash
# Test deployment without applying changes
DRY_RUN=true ./scripts/deploy_argo_workflows.sh
```

### Manual Testing

```bash
# Validate workflow YAML syntax
kubectl apply -f k8s/argo/mizzou-pipeline-workflow.yaml --dry-run=client

# Submit test workflow
argo submit --from cronwf/mizzou-news-pipeline -n production --name test-run-1

# Watch test workflow
argo watch test-run-1 -n production

# Get logs
argo logs test-run-1 -n production
```

## Cost Analysis

### Resource Costs

| Component | Current | With Argo | Change |
|-----------|---------|-----------|--------|
| CronJobs | $20-25/mo | $0 (replaced) | -$20/mo |
| Argo controller | $0 | $3/mo | +$3/mo |
| Argo server (UI) | $0 | $5/mo | +$5/mo |
| Workflow storage | $0 | $1/mo | +$1/mo |
| Workflow execution | $0 | $20-25/mo | +$20/mo |
| **Total** | **$20-25/mo** | **$29-34/mo** | **+$9/mo** |

**ROI**: $9/month for production-grade orchestration, visibility, and reliability.

## Advanced Topics

### Custom Workflows

To create a custom workflow for a new dataset:

1. Copy an existing workflow file (e.g., `mizzou-pipeline-workflow.yaml`)
2. Update metadata (name, labels)
3. Update schedule (offset from other workflows)
4. Update dataset name in commands
5. Adjust rate limiting for dataset
6. Apply workflow: `kubectl apply -f k8s/argo/my-dataset-workflow.yaml`

### Workflow Templates

To create reusable workflow templates:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: WorkflowTemplate
metadata:
  name: news-pipeline-template
  namespace: production
spec:
  # Define reusable templates here
  templates:
  - name: discovery-template
    inputs:
      parameters:
      - name: dataset
      - name: source-limit
    # ... template definition
```

### Notifications

Integrate with Slack or email for workflow notifications:

```yaml
spec:
  hooks:
    exit:
      template: send-notification
```

See Argo Workflows documentation for details: https://argoproj.github.io/argo-workflows/

## References

- [Argo Workflows Documentation](https://argoproj.github.io/argo-workflows/)
- [Argo CronWorkflow Guide](https://argoproj.github.io/argo-workflows/cron-workflows/)
- [Issue #79: Implement Argo Workflows](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/79)
- [Orchestration Architecture](docs/ORCHESTRATION_ARCHITECTURE.md)

## Support

For issues or questions:
1. Check this guide and troubleshooting section
2. Review Argo Workflows documentation
3. Check workflow logs and events
4. Create a GitHub issue with workflow YAML and logs
