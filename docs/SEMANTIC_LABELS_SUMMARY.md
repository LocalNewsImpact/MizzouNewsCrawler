# Implementation Summary: Semantic Labels for Argo Workflows

## What Was Done

Added semantic labels to all Argo Workflow templates to enable easy log correlation and filtering of jobs within the same workflow run.

## Changes Made

### 1. Updated `k8s/argo/base-pipeline-workflow.yaml`

Added metadata labels to all five workflow templates:

- **discovery-step**: Added `stage: discovery`, `workflow-name`, `workflow-uid`
- **verification-step**: Added `stage: verification`, `workflow-name`, `workflow-uid`
- **extraction-step**: Added `stage: extraction`, `workflow-name`, `workflow-uid`
- **wait-for-candidates**: Added `stage: wait-candidates`, `workflow-name`, `workflow-uid`
- **wait-for-verified**: Added `stage: wait-verified`, `workflow-name`, `workflow-uid`

### 2. Updated `k8s/argo/mizzou-pipeline-cronworkflow.yaml`

Added workflow-level metadata:

```yaml
workflowMetadata:
  labels:
    dataset: mizzou-missouri-state
    pipeline-type: scheduled
    schedule: every-6-hours
```

### 3. Created Documentation

- **docs/ARGO_LOG_CORRELATION.md** - Comprehensive guide with examples
- **docs/ARGO_QUICK_REFERENCE.md** - Quick reference card for common queries

## Understanding the Job Names

### Before (What the Numbers Mean)

```text
mizzou-news-pipeline-1761156000-extraction-step-3155092536
                     ↑           ↑               ↑
                     |           |               └─ Argo hash (unchangeable)
                     |           └─────────────── Template name
                     └────────────────────────── Unix timestamp (Oct 22, 2025 18:00:00 UTC)
```

The numbers represent:

1. **1761156000** = Unix timestamp = scheduled run time (SEMANTIC but not human-readable)
1. **3155092536** = Argo-generated hash for unique node ID (NOT semantic)

### After (How to Use Labels)

We can't change the naming convention (Argo controls it), but we added **labels** that make correlation trivial:

| Label | Purpose | Example |
|-------|---------|---------|
| `workflow-name` | Full workflow instance name | `mizzou-news-pipeline-1761156000` |
| `workflow-uid` | Immutable UUID | `0adb260d-d970-46e6-aa9c-cfbca77e0c85` |
| `stage` | Pipeline stage | `discovery`, `extraction`, `verification` |

## Benefits

### Before Labels

To find all jobs in a workflow run, you had to:

1. Get the workflow name
1. Manually construct pod name patterns
1. Filter through all pods hoping to match the right ones

```bash
# Hard way - error-prone pattern matching
kubectl get pods -n production | grep "mizzou-news-pipeline-1761156000"
```

### After Labels

Simply filter by the semantic labels:

```bash
# Easy way - precise label selection
kubectl logs -n production -l workflow-name=mizzou-news-pipeline-1761156000 --all-containers=true
```

## Common Use Cases

### 1. Track All Jobs in a Workflow Run

```bash
kubectl logs -n production -l workflow-name=mizzou-news-pipeline-1761156000 --all-containers=true
```

### 2. Monitor a Specific Pipeline Stage

```bash
kubectl logs -n production -l stage=extraction -f
```

### 3. Debug Failures

```bash
# Find failed workflows
kubectl get workflows -n production --field-selector=status.phase=Failed | tail -5

# Get logs from failed extraction
kubectl logs -n production -l workflow-name=<NAME>,stage=extraction --tail=200
```

### 4. Combine Labels for Precision

```bash
# Extraction jobs from a specific workflow
kubectl logs -n production -l stage=extraction,workflow-name=mizzou-news-pipeline-1761156000

# All jobs for Mizzou dataset
kubectl get pods -n production -l dataset=mizzou-missouri-state
```

## Deployment

Changes have been applied to the cluster:

```bash
✅ kubectl apply -f k8s/argo/base-pipeline-workflow.yaml
✅ kubectl apply -f k8s/argo/mizzou-pipeline-cronworkflow.yaml
```

New workflows triggered after this change will have the semantic labels. Existing workflows retain their old labels.

## Testing

To test the labels on the next scheduled run (6-hour intervals):

```bash
# Wait for next workflow to start (check at 00:00, 06:00, 12:00, 18:00 UTC)
kubectl get workflows -n production -w

# Once started, test label filtering
kubectl get pods -n production -l stage=discovery
kubectl logs -n production -l workflow-name=<NEW_WORKFLOW_NAME> -f
```

## Files Modified

- `k8s/argo/base-pipeline-workflow.yaml` - Added labels to all 5 templates
- `k8s/argo/mizzou-pipeline-cronworkflow.yaml` - Added workflowMetadata

## Files Created

- `docs/ARGO_LOG_CORRELATION.md` - Full documentation (190 lines)
- `docs/ARGO_QUICK_REFERENCE.md` - Quick reference card (50 lines)
- `docs/SEMANTIC_LABELS_SUMMARY.md` - This file

## Success Metrics

✅ All workflow templates have stage labels  
✅ All templates have workflow-name and workflow-uid labels  
✅ CronWorkflow has workflow-level metadata  
✅ Documentation created for users  
✅ Changes deployed to production cluster  

## Next Steps

1. Monitor the next scheduled workflow run (every 6 hours)
1. Verify labels are present on new pods: `kubectl get pods -n production --show-labels`
1. Test log correlation queries from the quick reference
1. Share documentation with team for onboarding

## References

- [Argo Workflows Labels Documentation](https://argoproj.github.io/argo-workflows/variables/)
- Full guide: `docs/ARGO_LOG_CORRELATION.md`
- Quick reference: `docs/ARGO_QUICK_REFERENCE.md`
