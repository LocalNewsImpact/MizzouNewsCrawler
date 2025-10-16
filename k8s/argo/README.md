# Argo Workflows Configuration

This directory contains Argo Workflows configurations for production pipeline orchestration.

## Files

### Core Workflow Files

- **`rbac.yaml`**: RBAC configuration (ServiceAccount, Role, RoleBinding)
  - Defines permissions needed for workflows to run
  - Must be applied before workflows

- **`base-pipeline-workflow.yaml`**: Reusable WorkflowTemplate
  - Dataset-agnostic pipeline template
  - Three steps: Discovery → Verification → Extraction
  - Parameterized for rate limiting and resource configuration
  - Used by all dataset-specific CronWorkflows

### Dataset-Specific CronWorkflows

- **`mizzou-pipeline-cronworkflow.yaml`**: Mizzou dataset pipeline
  - Runs every 6 hours at :00 (00:00, 06:00, 12:00, 18:00 UTC)
  - Moderate rate limiting (5-15s between requests)
  - Production-ready configuration

### Templates

- **`dataset-pipeline-template.yaml`**: Template for new datasets
  - Copy and customize for new datasets
  - Includes documentation on rate limiting options
  - Examples for different bot protection levels

## Quick Start

### Deploy Everything

```bash
# From repository root
./scripts/deploy_argo_workflows.sh
```

### Deploy Manually

```bash
# 1. Deploy RBAC
kubectl apply -f k8s/argo/rbac.yaml

# 2. Deploy base template
kubectl apply -f k8s/argo/base-pipeline-workflow.yaml

# 3. Deploy Mizzou CronWorkflow
kubectl apply -f k8s/argo/mizzou-pipeline-cronworkflow.yaml
```

### Verify Deployment

```bash
# Check CronWorkflows
kubectl get cronworkflow -n production

# Check WorkflowTemplate
kubectl get workflowtemplate -n production

# Check RBAC
kubectl get serviceaccount argo-workflow -n production
kubectl get role argo-workflow-role -n production
kubectl get rolebinding argo-workflow-binding -n production
```

## Adding a New Dataset

1. Copy the template:
   ```bash
   cp k8s/argo/dataset-pipeline-template.yaml k8s/argo/my-dataset-pipeline-cronworkflow.yaml
   ```

2. Edit the file:
   - Update `metadata.name` with your dataset name
   - Update `metadata.labels.dataset`
   - Adjust `spec.schedule` (offset from other datasets to avoid conflicts)
   - Update all parameter values for your dataset
   - Configure rate limiting based on target site's bot protection

3. Deploy:
   ```bash
   kubectl apply -f k8s/argo/my-dataset-pipeline-cronworkflow.yaml
   ```

## Configuration

### Schedule Format

CronWorkflows use standard cron syntax:
- `0 */6 * * *` - Every 6 hours at :00 (00:00, 06:00, 12:00, 18:00)
- `30 */6 * * *` - Every 6 hours at :30 (00:30, 06:30, 12:30, 18:30)
- `0 0 * * *` - Daily at midnight

### Rate Limiting Options

**Conservative (low bot detection):**
```yaml
inter-request-min: "2.0"
inter-request-max: "5.0"
batch-sleep: "10.0"
captcha-backoff-base: "900"    # 15 minutes
captcha-backoff-max: "3600"    # 1 hour
```

**Moderate (typical):**
```yaml
inter-request-min: "5.0"
inter-request-max: "15.0"
batch-sleep: "30.0"
captcha-backoff-base: "1800"   # 30 minutes
captcha-backoff-max: "7200"    # 2 hours
```

**Aggressive (strong bot protection):**
```yaml
inter-request-min: "90.0"
inter-request-max: "180.0"
batch-sleep: "420.0"
captcha-backoff-base: "7200"   # 2 hours
captcha-backoff-max: "21600"   # 6 hours
```

## Monitoring

### List Workflows

```bash
# List all CronWorkflows
kubectl get cronworkflow -n production

# List workflow executions
kubectl get workflows -n production

# Watch workflows in real-time
kubectl get workflows -n production -w
```

### Access Argo UI

```bash
# Port forward to Argo server
kubectl -n argo port-forward svc/argo-server 2746:2746

# Open in browser
open https://localhost:2746
```

### View Logs

```bash
# View logs for a specific workflow
kubectl logs -n production -l workflows.argoproj.io/workflow=<workflow-name>

# Follow logs in real-time
kubectl logs -n production -l workflows.argoproj.io/workflow=<workflow-name> -f
```

## Management

### Suspend CronWorkflow

```bash
# Stop scheduled runs (workflows won't trigger)
kubectl patch cronworkflow mizzou-news-pipeline -n production -p '{"spec":{"suspend":true}}'
```

### Resume CronWorkflow

```bash
# Re-enable scheduled runs
kubectl patch cronworkflow mizzou-news-pipeline -n production -p '{"spec":{"suspend":false}}'
```

### Trigger Manual Run

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

### Delete Workflow Execution

```bash
# Delete a specific workflow execution
kubectl delete workflow <workflow-name> -n production
```

## Troubleshooting

### Workflow Won't Start

Check if suspended:
```bash
kubectl get cronworkflow mizzou-news-pipeline -n production -o jsonpath='{.spec.suspend}'
```

Check schedule:
```bash
kubectl get cronworkflow mizzou-news-pipeline -n production -o jsonpath='{.spec.schedule}'
```

### Workflow Fails

View workflow details:
```bash
kubectl get workflow <workflow-name> -n production -o yaml
```

Check pod events:
```bash
kubectl describe pod <pod-name> -n production
```

View logs:
```bash
kubectl logs <pod-name> -n production
```

## Documentation

For complete documentation, see:
- [docs/ARGO_SETUP.md](../../docs/ARGO_SETUP.md) - Complete setup and usage guide
- [docs/ARGO_DEPLOYMENT_PLAN.md](../../docs/ARGO_DEPLOYMENT_PLAN.md) - Deployment plan and procedures

## References

- Issue #82: Implement Production Pipeline Orchestration with Argo Workflows
- [Argo Workflows Documentation](https://argoproj.github.io/argo-workflows/)
- [Argo CronWorkflow Guide](https://argoproj.github.io/argo-workflows/cron-workflows/)
