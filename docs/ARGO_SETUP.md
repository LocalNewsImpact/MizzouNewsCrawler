# Argo Workflows Setup Guide

## Overview

This guide explains how to set up and use Argo Workflows for pipeline orchestration in the Mizzou News Crawler project.

## What is Argo Workflows?

Argo Workflows is a Kubernetes-native workflow engine that provides:
- **DAG Visualization**: See pipeline progress in real-time
- **Retry Logic**: Automatically retry failed steps
- **Conditional Execution**: Skip steps based on previous results
- **Resource Management**: Control CPU and memory usage
- **Observability**: Built-in logging and metrics

## Architecture

### Pipeline Flow

```
Discovery (5-10 min) → Verification (10-30 min) → Extraction (30-60 min)
          ↓                    ↓                         ↓
    candidate_links       candidate_links            articles
   (status=discovered)    (status=article)      (status=extracted)
```

### Components

1. **WorkflowTemplate** (`base-pipeline-workflow.yaml`): Reusable template defining the three-step pipeline
2. **CronWorkflow** (`mizzou-pipeline-cronworkflow.yaml`): Scheduled execution of the pipeline
3. **RBAC** (`rbac.yaml`): Permissions for workflows to access resources

## Installation

### Prerequisites

- kubectl configured with access to your GKE cluster
- Access to the `production` namespace
- Argo Workflows CLI (optional, for advanced usage)

### Step 1: Deploy Argo Workflows

Use the automated deployment script:

```bash
# From repository root
./scripts/deploy_argo_workflows.sh
```

Or deploy manually:

```bash
# Create argo namespace
kubectl create namespace argo

# Install Argo Workflows
kubectl apply -n argo -f https://github.com/argoproj/argo-workflows/releases/download/v3.5.5/install.yaml

# Wait for deployment
kubectl wait --for=condition=available --timeout=300s -n argo deployment/workflow-controller
kubectl wait --for=condition=available --timeout=300s -n argo deployment/argo-server
```

### Step 2: Deploy RBAC and Workflows

```bash
# Deploy RBAC
kubectl apply -f k8s/argo/rbac.yaml

# Deploy workflow template
kubectl apply -f k8s/argo/base-pipeline-workflow.yaml

# Deploy Mizzou CronWorkflow
kubectl apply -f k8s/argo/mizzou-pipeline-cronworkflow.yaml
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

### Managing CronWorkflows

#### List CronWorkflows

```bash
kubectl get cronworkflow -n production
```

#### View Schedule

```bash
kubectl get cronworkflow mizzou-news-pipeline -n production -o jsonpath='{.spec.schedule}'
```

#### Suspend CronWorkflow

```bash
# Stop scheduled runs
kubectl patch cronworkflow mizzou-news-pipeline -n production -p '{"spec":{"suspend":true}}'
```

#### Resume CronWorkflow

```bash
# Re-enable scheduled runs
kubectl patch cronworkflow mizzou-news-pipeline -n production -p '{"spec":{"suspend":false}}'
```

### Managing Workflows

#### List Workflows

```bash
# List all workflows
kubectl get workflows -n production

# Watch workflows in real-time
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
```

#### View Logs

```bash
# View logs for a specific workflow
kubectl logs -n production -l workflows.argoproj.io/workflow=<workflow-name>

# Follow logs in real-time
kubectl logs -n production -l workflows.argoproj.io/workflow=<workflow-name> -f
```

#### Delete Workflow

```bash
# Delete a specific workflow execution
kubectl delete workflow <workflow-name> -n production
```

## Configuration

### Schedule

Mizzou pipeline runs every 6 hours:
- 00:00 UTC
- 06:00 UTC
- 12:00 UTC
- 18:00 UTC

To change schedule, edit `spec.schedule` in the CronWorkflow YAML.

### Rate Limiting

Mizzou uses moderate rate limiting:
- **Inter-request**: 5-15 seconds
- **Batch sleep**: 30 seconds
- **CAPTCHA backoff**: 30 minutes - 2 hours

### Resource Limits

Each step has resource requests and limits:
- **Discovery**: 200m CPU, 2Gi memory (request) / 1000m CPU, 4Gi memory (limit)
- **Verification**: 250m CPU, 1Gi memory (request) / 1000m CPU, 3Gi memory (limit)
- **Extraction**: 250m CPU, 1Gi memory (request) / 1000m CPU, 3Gi memory (limit)

## Adding New Datasets

To create a pipeline for a new dataset:

1. Copy the dataset template:
   ```bash
   cp k8s/argo/dataset-pipeline-template.yaml k8s/argo/my-dataset-pipeline-cronworkflow.yaml
   ```

2. Edit the file and update:
   - `metadata.name`: Your dataset name
   - `metadata.labels.dataset`: Your dataset name
   - `spec.schedule`: Offset from other pipelines (e.g., `30 */6 * * *`)
   - All parameter values for your dataset
   - Rate limiting based on target site's bot protection

3. Deploy:
   ```bash
   kubectl apply -f k8s/argo/my-dataset-pipeline-cronworkflow.yaml
   ```

## Monitoring

### Workflow Status

```bash
# Get workflow status
kubectl get workflow <workflow-name> -n production -o yaml

# Get workflow events
kubectl describe workflow <workflow-name> -n production
```

### Resource Usage

```bash
# Check pod resource usage
kubectl top pods -n production -l workflows.argoproj.io/workflow=<workflow-name>
```

### Metrics

Argo provides Prometheus metrics:

```bash
# Port forward to metrics endpoint
kubectl -n argo port-forward svc/workflow-controller-metrics 9090:9090

# Access metrics
curl http://localhost:9090/metrics
```

## Troubleshooting

### Workflow Won't Start

Check if CronWorkflow is suspended:
```bash
kubectl get cronworkflow mizzou-news-pipeline -n production -o jsonpath='{.spec.suspend}'
```

### Workflow Fails

View workflow status:
```bash
kubectl get workflow <workflow-name> -n production -o yaml
```

Check pod events:
```bash
kubectl describe pod <pod-name> -n production
```

Check logs:
```bash
kubectl logs <pod-name> -n production
```

### Step Hangs

Check pod status:
```bash
kubectl get pods -n production -l workflows.argoproj.io/workflow=<workflow-name>
```

Force delete stuck pod:
```bash
kubectl delete pod <pod-name> -n production --grace-period=0 --force
```

## Rollback

If you need to rollback to the old system:

### Using Script

```bash
# Dry run to see what would be deleted
DRY_RUN=true ./scripts/rollback_argo_workflows.sh

# Execute rollback
./scripts/rollback_argo_workflows.sh
```

### Manual Rollback

```bash
# 1. Suspend Argo CronWorkflows
kubectl patch cronworkflow mizzou-news-pipeline -n production -p '{"spec":{"suspend":true}}'

# 2. Delete running workflows
kubectl delete workflows -n production --all

# 3. Delete CronWorkflows
kubectl delete cronworkflow mizzou-news-pipeline -n production

# 4. Delete WorkflowTemplate
kubectl delete workflowtemplate news-pipeline-template -n production

# 5. Delete RBAC resources
kubectl delete -f k8s/argo/rbac.yaml

# 6. Re-enable old CronJobs (if they were suspended)
kubectl patch cronjob mizzou-discovery -n production -p '{"spec":{"suspend":false}}'
```

## Cost Analysis

Estimated monthly costs:

| Component | Cost |
|-----------|------|
| Argo controller | $3/mo |
| Argo server (UI) | $5/mo |
| Workflow storage | $1/mo |
| Workflow execution | $20-25/mo |
| **Total** | **$29-34/mo** |

**ROI**: ~$9/month additional for production-grade orchestration, visibility, and reliability.

## References

- [Argo Workflows Documentation](https://argoproj.github.io/argo-workflows/)
- [Argo CronWorkflow Guide](https://argoproj.github.io/argo-workflows/cron-workflows/)
- [Issue #82: Implement Argo Workflows](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/82)

## Support

For issues or questions:
1. Check this guide and troubleshooting section
2. Review Argo Workflows documentation
3. Check workflow logs and events
4. Create a GitHub issue with workflow YAML and logs
