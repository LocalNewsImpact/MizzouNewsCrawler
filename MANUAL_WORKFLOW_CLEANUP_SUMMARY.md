# Manual Workflow Cleanup Summary

**Date**: October 20, 2025  
**Action**: Cleaned up broken manual workflows  
**Status**: ✅ COMPLETE

---

## Actions Completed

### 1. ✅ Deleted Broken Running Workflow

```bash
kubectl delete workflow mizzou-news-pipeline-manual-2zstf -n production
```

**Result**: Stopped the workflow stuck in `CreateContainerConfigError` for 3+ hours

---

### 2. ✅ Cleaned Up Failed Manual Workflows

**Deleted workflows:**
- `mizzou-news-pipeline-manual-55q2d` - Failed: invalid spec: spec.entrypoint is required
- `mizzou-news-pipeline-manual-7xznr` - Failed: Stopped with strategy 'Stop'
- `mizzou-news-pipeline-manual-sg8p9` - Failed: child failed
- `mizzou-news-pipeline-manual-w7jj8` - Failed: child failed
- `mizzou-news-pipeline-manual-wj79p` - Failed: Stopped with strategy 'Stop'
- `mizzou-news-pipeline-manual-xvggj` - Failed: Stopped with strategy 'Stop'
- `mizzou-news-pipeline-manual-ztb8n` - Failed: inputs.parameters.days-back was not supplied
- `mizzou-news-pipeline-manual-nz726` - Error: workflowtemplates.argoproj.io "mizzou-news-pipeline" not found

**Total deleted**: 8 broken workflows

---

### 3. ✅ Created Proper Manual Trigger Scripts

#### Script 1: `scripts/trigger_manual_pipeline.sh`
- Uses Argo CLI (`argo submit`)
- Requires: `brew install argo`
- Interactive confirmation
- Watches workflow progress
- All correct parameters

**Usage:**
```bash
# Default parameters (50 sources, 50 articles, 7 days)
./scripts/trigger_manual_pipeline.sh

# Custom parameters
./scripts/trigger_manual_pipeline.sh "Mizzou-Missouri-State" 100 75 14
```

#### Script 2: `scripts/trigger_manual_pipeline_kubectl.sh`
- Uses kubectl (no Argo CLI needed)
- Works with standard Kubernetes tools
- Same functionality as Argo CLI version

**Usage:**
```bash
# Default parameters
./scripts/trigger_manual_pipeline_kubectl.sh

# Custom parameters
./scripts/trigger_manual_pipeline_kubectl.sh "Mizzou-Missouri-State" 100
```

---

## Current Workflow State

### ✅ Successful Workflows (Kept)

- `mizzou-news-pipeline-manual-2l84j` - Succeeded 2d1h ago (good manual run)
- `mizzou-news-pipeline-manual-qpg9t` - Succeeded 15h ago (good manual run)

### 🔄 CronWorkflow Status

```
mizzou-news-pipeline-1760961600 - Running (started 3h49m ago)
```

**CronWorkflow is working correctly** - runs every 6 hours

---

## Key Differences: OLD vs NEW Manual Trigger

### ❌ OLD Method (WRONG - Was causing failures)

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  generateName: mizzou-news-pipeline-manual-
spec:
  entrypoint: news-pipeline              # ❌ OLD entrypoint
  imagePullSecrets:
  - name: gcr-json-key                   # ❌ WRONG secret
  templates:
  - name: news-pipeline                  # ❌ Inline template
    steps: [...]                         # ❌ Hard-coded steps
  - name: discovery
    container:
      envFrom:
      - secretRef:
          name: mizzou-crawler-secrets   # ❌ DOESN'T EXIST
```

**Problems:**
- Used wrong secrets (`mizzou-crawler-secrets`, `gcr-json-key`)
- Inline template instead of referencing WorkflowTemplate
- No Cloud SQL connector
- Missing proper database configuration

---

### ✅ NEW Method (CORRECT - Scripts use this)

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  generateName: mizzou-news-pipeline-manual-
  labels:
    trigger-type: manual
spec:
  workflowTemplateRef:
    name: news-pipeline-template         # ✅ Uses WorkflowTemplate
  arguments:
    parameters:
    - name: dataset
      value: "Mizzou-Missouri-State"
    - name: source-limit
      value: "50"
    # ... all parameters
```

**Benefits:**
- ✅ References `news-pipeline-template` (same as CronWorkflow)
- ✅ All configuration comes from template (Cloud SQL, secrets, etc.)
- ✅ Only passes parameters as arguments
- ✅ Automatically uses correct secrets and sidecars
- ✅ Consistent with CronWorkflow behavior

---

## Verification

### Check Remaining Workflows

```bash
kubectl get workflows -n production | grep manual
```

**Output:**
```
mizzou-news-pipeline-manual-2l84j   Succeeded   2d1h    
mizzou-news-pipeline-manual-qpg9t   Succeeded   15h
```

✅ Only successful manual workflows remain

### Check CronWorkflow

```bash
kubectl get cronworkflow mizzou-news-pipeline -n production
```

✅ CronWorkflow is active and running every 6 hours

---

## Documentation Updates

### Created Files

1. **`MANUAL_WORKFLOW_ISSUE.md`** - Full root cause analysis
2. **`scripts/trigger_manual_pipeline.sh`** - Argo CLI method
3. **`scripts/trigger_manual_pipeline_kubectl.sh`** - kubectl method

### Updated Files

None - scripts are new additions

---

## Prevention Measures

### Short Term ✅

- [x] Deleted all broken workflows
- [x] Created correct manual trigger scripts
- [x] Documented the issue

### Medium Term (Recommended)

- [ ] Update `scripts/deploy_argo_workflows.sh` to remove old example (line 217)
- [ ] Update `docs/ARGO_SETUP.md` with new manual trigger method
- [ ] Add note to `k8s/argo/README.md` about using scripts
- [ ] Investigate who has Argo UI access (potential source of bad submissions)

### Long Term (Consider)

- [ ] Add RBAC restrictions on workflow submission
- [ ] Create admission webhook to validate workflows use templates
- [ ] Add monitoring/alerting for failed workflow submissions
- [ ] Create self-service UI with pre-validated forms

---

## Next Steps

### If Manual Trigger Needed

Use one of the new scripts:

```bash
# Method 1: With Argo CLI
./scripts/trigger_manual_pipeline.sh

# Method 2: With kubectl only
./scripts/trigger_manual_pipeline_kubectl.sh
```

### Monitor CronWorkflow

The automatic runs every 6 hours should handle regular pipeline execution:

```bash
# Check schedule
kubectl get cronworkflow mizzou-news-pipeline -n production

# Watch for next run
kubectl get workflows -n production -w
```

### If Issues Persist

1. Check Argo UI access logs
2. Search for external automation/scripts
3. Review who has kubectl access to production namespace

---

## Related Documentation

- **Root Cause Analysis**: `MANUAL_WORKFLOW_ISSUE.md`
- **Deployment Guide**: `docs/ARGO_SETUP.md`
- **Workflow Templates**: `k8s/argo/base-pipeline-workflow.yaml`
- **CronWorkflow Config**: `k8s/argo/mizzou-pipeline-cronworkflow.yaml`

---

## Summary

✅ **Problem Solved**: All 8 broken manual workflows deleted  
✅ **Tools Created**: 2 scripts for correct manual triggering  
✅ **Documentation**: Full analysis and prevention measures documented  
⚠️ **Action Needed**: Find who/what was creating the bad workflows

**CronWorkflow continues to run correctly every 6 hours** - manual triggers should rarely be needed.
