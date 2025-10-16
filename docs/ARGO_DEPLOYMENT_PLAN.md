# Argo Workflows Deployment Plan

## Overview

This document outlines the deployment plan for implementing Argo Workflows as described in Issue #82.

## Implementation Status

### ✅ Completed

1. **RBAC Configuration** (`k8s/argo/rbac.yaml`)
   - ServiceAccount: `argo-workflow`
   - Role with required permissions
   - RoleBinding to attach role to service account

2. **Base Workflow Template** (`k8s/argo/base-pipeline-workflow.yaml`)
   - Reusable WorkflowTemplate for any dataset
   - Three-step pipeline: Discovery → Verification → Extraction
   - Parameterized rate limiting and resource configuration
   - Automatic retry logic with exponential backoff

3. **Mizzou Pipeline** (`k8s/argo/mizzou-pipeline-cronworkflow.yaml`)
   - CronWorkflow running every 6 hours at :00 (00:00, 06:00, 12:00, 18:00 UTC)
   - Moderate rate limiting (5-15s between requests)
   - Uses base template with Mizzou-specific parameters

4. **Dataset Template** (`k8s/argo/dataset-pipeline-template.yaml`)
   - Template for creating new dataset pipelines
   - Documentation on how to customize for different bot protection levels

5. **Deployment Scripts**
   - `scripts/deploy_argo_workflows.sh` - Automated deployment with dry-run support
   - `scripts/rollback_argo_workflows.sh` - Safe rollback mechanism

6. **Documentation**
   - `docs/ARGO_SETUP.md` - Complete setup and usage guide

7. **Tests** (`tests/test_argo_workflows.py`)
   - Comprehensive test suite for YAML validation
   - Tests for workflow structure, configuration, and RBAC

## Deployment Phases

### Phase 1: Pre-Deployment Validation (15 minutes)

#### Prerequisites Check
```bash
# Verify kubectl access
kubectl get nodes

# Verify production namespace exists
kubectl get namespace production

# Verify required secrets exist
kubectl get secret cloudsql-db-credentials -n production
kubectl get secret origin-proxy-credentials -n production
```

#### Backup Current CronJobs
```bash
# Create backup directory
mkdir -p /tmp/argo-deployment-backup

# Backup existing CronJobs
kubectl get cronjob -n production -o yaml > /tmp/argo-deployment-backup/cronjobs-backup.yaml

# Note: Don't delete these yet, we'll run Argo in parallel first
```

### Phase 2: Argo Installation (10 minutes)

```bash
# Use deployment script with dry-run first
DRY_RUN=true ./scripts/deploy_argo_workflows.sh

# If dry-run looks good, deploy for real
./scripts/deploy_argo_workflows.sh
```

Or manually:

```bash
# Create argo namespace
kubectl create namespace argo

# Install Argo Workflows
kubectl apply -n argo -f https://github.com/argoproj/argo-workflows/releases/download/v3.5.5/install.yaml

# Wait for Argo to be ready
kubectl wait --for=condition=available --timeout=300s -n argo deployment/workflow-controller
kubectl wait --for=condition=available --timeout=300s -n argo deployment/argo-server

# Verify installation
kubectl get pods -n argo
```

### Phase 3: Deploy Workflows (5 minutes)

```bash
# Deploy RBAC
kubectl apply -f k8s/argo/rbac.yaml

# Deploy base template
kubectl apply -f k8s/argo/base-pipeline-workflow.yaml

# Deploy Mizzou CronWorkflow (initially will start based on schedule)
kubectl apply -f k8s/argo/mizzou-pipeline-cronworkflow.yaml

# Verify deployment
kubectl get cronworkflow -n production
kubectl get workflowtemplate -n production
```

### Phase 4: Initial Testing (1-2 hours)

#### Test 1: Manual Trigger

```bash
# Trigger a manual run to test immediately
kubectl create -n production -f - <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  generateName: mizzou-news-pipeline-test-
spec:
  workflowTemplateRef:
    name: mizzou-news-pipeline
EOF

# Watch execution
kubectl get workflows -n production -w

# Check logs
kubectl logs -n production -l workflows.argoproj.io/workflow=<workflow-name> -f
```

**Success Criteria:**
- Discovery step completes successfully
- Verification step runs after discovery
- Extraction step runs after verification
- Database shows articles in 'extracted' status
- No rate limit violations

#### Test 2: Access Argo UI

```bash
# Port forward to Argo server
kubectl -n argo port-forward svc/argo-server 2746:2746

# Open https://localhost:2746 in browser
# Verify you can see the workflow execution and logs
```

### Phase 5: Parallel Operation (24-48 hours)

#### Option A: Suspend Old CronJobs (Recommended)

```bash
# Suspend old CronJobs (don't delete yet)
kubectl patch cronjob processor-cronjob -n production -p '{"spec":{"suspend":true}}'
kubectl patch cronjob crawler-cronjob -n production -p '{"spec":{"suspend":true}}'

# Check they are suspended
kubectl get cronjobs -n production
```

#### Option B: Let Both Run (Monitor for Conflicts)

- Monitor for duplicate extractions
- Watch for rate limit violations
- Compare resource usage

#### Monitoring During Parallel Operation

```bash
# Check scheduled runs
kubectl get cronworkflow mizzou-news-pipeline -n production

# View workflow history
kubectl get workflows -n production --sort-by=.status.finishedAt

# Check for failures
kubectl get workflows -n production | grep -i failed

# Monitor database article counts
# Connect to database and run:
# SELECT status, COUNT(*) FROM articles WHERE created_at > NOW() - INTERVAL '24 hours' GROUP BY status;
```

**Success Metrics (24 hours):**
- 4 successful workflow runs (one every 6 hours)
- ~40-50 articles extracted per run
- No increase in rate limit violations
- No resource conflicts
- Clear visibility of pipeline status in Argo UI

### Phase 6: Cutover (15 minutes)

If parallel operation is successful:

```bash
# Delete old CronJobs
kubectl delete cronjob processor-cronjob -n production
kubectl delete cronjob crawler-cronjob -n production

# Note: processor-deployment should continue running for cleaning/ML/entities
# Verify it's still running:
kubectl get deployment processor-deployment -n production
```

### Phase 7: Monitoring (Ongoing)

#### Daily Checks
- Check workflow success rate: `kubectl get workflows -n production | grep -c Succeeded`
- Verify articles are being extracted: Query database
- Check for stuck workflows: `kubectl get workflows -n production | grep Running`

#### Weekly Checks
- Review Argo UI for any patterns in failures
- Check resource usage trends
- Verify no rate limit pattern changes

## Rollback Procedures

### Quick Rollback (If Issues in First 24 Hours)

```bash
# Suspend Argo CronWorkflow
kubectl patch cronworkflow mizzou-news-pipeline -n production -p '{"spec":{"suspend":true}}'

# Re-enable old CronJobs
kubectl patch cronjob processor-cronjob -n production -p '{"spec":{"suspend":false}}'
kubectl patch cronjob crawler-cronjob -n production -p '{"spec":{"suspend":false}}'
```

### Full Rollback (If Persistent Issues)

```bash
# Use rollback script
./scripts/rollback_argo_workflows.sh

# Or manually:
# 1. Suspend CronWorkflows
kubectl patch cronworkflow mizzou-news-pipeline -n production -p '{"spec":{"suspend":true}}'

# 2. Delete running workflows
kubectl delete workflows -n production --all

# 3. Delete CronWorkflows
kubectl delete cronworkflow mizzou-news-pipeline -n production

# 4. Delete WorkflowTemplate
kubectl delete workflowtemplate news-pipeline-template -n production

# 5. Delete RBAC resources
kubectl delete -f k8s/argo/rbac.yaml

# 6. Re-enable old CronJobs
kubectl apply -f /tmp/argo-deployment-backup/cronjobs-backup.yaml
```

## Success Criteria

### Immediate (Phase 2-3)
- ✅ Argo Workflows installed successfully
- ✅ All pods running in argo namespace
- ✅ RBAC configured correctly
- ✅ Workflows deployed and visible

### Short-term (Phase 4-5, 24-48 hours)
- ✅ Manual workflow execution successful
- ✅ Scheduled workflows running on time
- ✅ 4+ successful runs per day
- ✅ Article extraction rate ≥ baseline
- ✅ No increase in rate limit violations
- ✅ No resource conflicts

### Long-term (1-2 weeks)
- ✅ 28+ successful workflow runs (4/day × 7 days)
- ✅ ~1,400 articles extracted
- ✅ <1% failure rate (excluding expected CAPTCHAs/404s)
- ✅ Old CronJobs deleted
- ✅ Team comfortable with Argo operations

## Cost Analysis

| Component | Current | With Argo | Change |
|-----------|---------|-----------|--------|
| CronJobs | $20-25/mo | $0 (replaced) | -$20/mo |
| Argo controller | $0 | $3/mo | +$3/mo |
| Argo server (UI) | $0 | $5/mo | +$5/mo |
| Workflow storage | $0 | $1/mo | +$1/mo |
| Workflow execution | $0 | $20-25/mo | +$20/mo |
| **Total** | **$20-25/mo** | **$29-34/mo** | **+$9/mo** |

**ROI**: $9/month for production-grade orchestration, visibility, and reliability.

## Troubleshooting

### Workflow Won't Start
- Check if CronWorkflow is suspended: `kubectl get cronworkflow mizzou-news-pipeline -n production -o jsonpath='{.spec.suspend}'`
- Check schedule: `kubectl get cronworkflow mizzou-news-pipeline -n production -o jsonpath='{.spec.schedule}'`
- Check last execution: `kubectl get cronworkflow mizzou-news-pipeline -n production -o jsonpath='{.status.lastScheduledTime}'`

### Workflow Fails
- View workflow details: `kubectl get workflow <name> -n production -o yaml`
- Check pod events: `kubectl describe pod <pod-name> -n production`
- View logs: `kubectl logs <pod-name> -n production`

### Step Hangs
- Check pod status: `kubectl get pods -n production -l workflows.argoproj.io/workflow=<name>`
- Check resource usage: `kubectl top pod <pod-name> -n production`
- Force delete if needed: `kubectl delete pod <pod-name> -n production --grace-period=0 --force`

## Contact

For questions or issues during deployment:
1. Check this deployment plan
2. Review docs/ARGO_SETUP.md
3. Check Argo Workflows logs
4. Create GitHub issue with details

## References

- Issue #82: Implement Production Pipeline Orchestration with Argo Workflows
- [Argo Workflows Documentation](https://argoproj.github.io/argo-workflows/)
- [Argo CronWorkflow Guide](https://argoproj.github.io/argo-workflows/cron-workflows/)
