# Manual Workflow Issue: Wrong Configuration

**Date**: October 20, 2025  
**Issue**: `mizzou-news-pipeline-manual-2zstf` failing with `CreateContainerConfigError`  
**Status**: 🔴 IDENTIFIED - Needs cleanup

---

## Problem Summary

Manual workflows with `generateName: mizzou-news-pipeline-manual-` are being created with an **OLD, INCORRECT configuration** that causes immediate failures.

### Error Details

```
Pod: mizzou-news-pipeline-manual-2zstf-discovery-1621139122
Status: CreateContainerConfigError
Message: secret "mizzou-crawler-secrets" not found
```

**Additional Issues:**
- `imagePullSecrets: gcr-json-key` - Unable to retrieve (doesn't exist or wrong name)
- Using old 4-step workflow structure instead of new template-based
- Missing Cloud SQL connector sidecar
- Missing proper database environment variables

---

## Root Cause Analysis

### Comparing Correct vs Incorrect Configs

#### ✅ **CORRECT** (CronWorkflow - Working)

```yaml
apiVersion: argoproj.io/v1alpha1
kind: CronWorkflow
metadata:
  name: mizzou-news-pipeline
spec:
  schedule: "0 */6 * * *"
  workflowSpec:
    serviceAccountName: argo-workflow
    templates:
    - name: mizzou-pipeline-wrapper
      steps:
      - - name: run-pipeline
          templateRef:
            name: news-pipeline-template  # ✅ Uses WorkflowTemplate
            template: pipeline
          arguments:
            parameters:
            - name: dataset
              value: "Mizzou-Missouri-State"
            - name: source-limit
              value: "50"
            # ... all proper parameters
```

**Key features:**
- ✅ Uses `news-pipeline-template` WorkflowTemplate
- ✅ Proper Cloud SQL connector with sidecar
- ✅ Correct secrets: `cloudsql-db-credentials`, `origin-proxy-credentials`
- ✅ Proper database environment variables
- ✅ 3-step pipeline: discovery → verification → extraction

#### ❌ **INCORRECT** (Manual Workflow - Failing)

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  generateName: mizzou-news-pipeline-manual-
spec:
  entrypoint: news-pipeline          # ❌ Old entrypoint name
  imagePullSecrets:
  - name: gcr-json-key               # ❌ Wrong/missing secret
  serviceAccountName: argo-workflow
  templates:
  - name: news-pipeline              # ❌ Inline template (old structure)
    steps:
    - - name: discover
        template: discovery
    - - name: extract
        template: extraction
    - - name: entity-extract          # ❌ Old 4-step structure
        template: entity-extraction
    - - name: analyze
        template: analysis
  
  - name: discovery
    container:
      image: us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:latest
      envFrom:
      - secretRef:
          name: mizzou-crawler-secrets  # ❌ Doesn't exist!
      # ❌ No Cloud SQL connector
      # ❌ No proper DB env vars
```

**Key problems:**
- ❌ Inline template instead of using `news-pipeline-template`
- ❌ Wrong secret: `mizzou-crawler-secrets` (doesn't exist)
- ❌ Wrong imagePullSecrets: `gcr-json-key` (can't retrieve)
- ❌ Old 4-step structure: discover → extract → entity-extract → analyze
- ❌ Missing Cloud SQL connector sidecar
- ❌ Missing database environment variables
- ❌ No verification step

---

## Who's Creating These?

### Evidence

1. **Workflow name pattern**: `generateName: mizzou-news-pipeline-manual-`
2. **Creation timing**: Multiple created over past 4 days
3. **No history in command line**: Not created via local kubectl commands
4. **Structure matches old docs**: Similar to example in `scripts/deploy_argo_workflows.sh:217`

### Possible Sources

**Most Likely:**
1. **Argo UI**: Someone submitting workflows through the web UI with old config
2. **Old script/automation**: An external script or CI job using outdated workflow spec
3. **Saved bookmark/curl command**: Someone re-running an old API call

**Less Likely:**
4. **Old WorkflowTemplate**: A lingering old template (checked - doesn't exist)
5. **CronWorkflow bug**: CronWorkflow is correct and working

### Verification Commands

```bash
# Check all WorkflowTemplates
kubectl get workflowtemplates -n production
# Output: Only "news-pipeline-template" exists (correct one)

# Check CronWorkflow
kubectl get cronworkflow mizzou-news-pipeline -n production -o yaml
# Output: Uses correct "news-pipeline-template" reference

# Check recent manual workflows
kubectl get workflows -n production | grep manual
# Shows multiple manual workflows over past 4 days
```

---

## Impact Assessment

### Current State

**CronWorkflow** (every 6 hours): ✅ **Working correctly**
- Last run: `mizzou-news-pipeline-1760961600` (3h42m ago, Running)
- Uses correct configuration
- No issues

**Manual Workflows**: ❌ **ALL FAILING**
- `mizzou-news-pipeline-manual-2zstf`: Running 3h18m (stuck in CreateContainerConfigError)
- `mizzou-news-pipeline-manual-w7jj8`: Failed 14h ago
- `mizzou-news-pipeline-manual-xvggj`: Failed 4d1h ago
- Multiple others failed with same issue

### Risk

- 🟢 **Production unaffected**: CronWorkflow working correctly
- 🟡 **Wasted resources**: Failed manual workflows consuming pods/compute
- 🟡 **Confusion**: Unclear who's creating these and why
- 🟡 **Support burden**: Recurring failures need investigation

---

## Solution

### Immediate Actions

#### 1. Stop/Delete Failing Manual Workflows

```bash
# Stop the currently running broken workflow
kubectl delete workflow mizzou-news-pipeline-manual-2zstf -n production

# Clean up other failed manual workflows
kubectl delete workflow -n production -l workflows.argoproj.io/phase=Failed
```

#### 2. Find the Source

**Check Argo UI access logs:**
```bash
# Check who's accessing Argo UI
kubectl logs -n argo deploy/argo-server --tail=500 | grep -i submit

# Check Argo server access
kubectl get events -n argo --sort-by='.lastTimestamp' | grep -i workflow
```

**Check for automation:**
```bash
# Search codebase for old workflow specs
grep -r "mizzou-crawler-secrets" .
grep -r "gcr-json-key" .
grep -r "news-pipeline.*entrypoint" .
```

**Check running processes:**
```bash
# Check if there's a CronJob or external trigger
kubectl get cronjobs -A
kubectl get jobs -A | grep mizzou
```

#### 3. Update Documentation

Remove/update the manual trigger example in:
- `scripts/deploy_argo_workflows.sh` (lines 217-222)
- `docs/ARGO_SETUP.md`
- `k8s/argo/README.md`

---

### Correct Way to Manually Trigger Workflow

#### Using Argo CLI (Recommended)

```bash
# Submit workflow using the correct template
argo submit -n production --from workflowtemplate/news-pipeline-template \
  --parameter dataset="Mizzou-Missouri-State" \
  --parameter source-limit="50" \
  --parameter max-articles="50" \
  --parameter days-back="7" \
  --parameter verify-batch-size="10" \
  --parameter verify-max-batches="100" \
  --parameter extract-limit="50" \
  --parameter extract-batches="40" \
  --parameter inter-request-min="5.0" \
  --parameter inter-request-max="15.0" \
  --parameter batch-sleep="30.0" \
  --parameter captcha-backoff-base="1800" \
  --parameter captcha-backoff-max="7200"
```

#### Using kubectl (Alternative)

```bash
kubectl create -n production -f - <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  generateName: mizzou-news-pipeline-manual-
spec:
  workflowTemplateRef:
    name: news-pipeline-template
  arguments:
    parameters:
    - name: dataset
      value: "Mizzou-Missouri-State"
    - name: source-limit
      value: "50"
    - name: max-articles
      value: "50"
    - name: days-back
      value: "7"
    - name: verify-batch-size
      value: "10"
    - name: verify-max-batches
      value: "100"
    - name: extract-limit
      value: "50"
    - name: extract-batches
      value: "40"
    - name: inter-request-min
      value: "5.0"
    - name: inter-request-max
      value: "15.0"
    - name: batch-sleep
      value: "30.0"
    - name: captcha-backoff-base
      value: "1800"
    - name: captcha-backoff-max
      value: "7200"
EOF
```

**Key differences from broken version:**
- ✅ Uses `workflowTemplateRef` to reference `news-pipeline-template`
- ✅ No inline templates or imagePullSecrets
- ✅ All configuration comes from the WorkflowTemplate
- ✅ Only passes parameters as arguments

---

### Preventive Measures

#### 1. Restrict Manual Workflow Submission

Add RBAC to prevent direct workflow creation (require using templates):

```yaml
# k8s/argo/rbac-restrictions.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: workflow-submitter
  namespace: production
rules:
# Allow reading WorkflowTemplates
- apiGroups: ["argoproj.io"]
  resources: ["workflowtemplates"]
  verbs: ["get", "list"]
# Allow creating Workflows only from templates
- apiGroups: ["argoproj.io"]
  resources: ["workflows"]
  verbs: ["create"]
  # Note: Can't enforce template-only via RBAC, need admission webhook
```

#### 2. Add Admission Webhook (Future)

Create a validating webhook to reject workflows without `workflowTemplateRef`.

#### 3. Update Documentation

Create clear guide: **"How to Manually Run Pipeline"**
- Remove old examples with inline templates
- Show only WorkflowTemplate-based submission
- Explain why inline templates are deprecated

---

## Investigation Checklist

### Completed ✅

- [x] Identified failing workflow: `mizzou-news-pipeline-manual-2zstf`
- [x] Found error: `CreateContainerConfigError: secret "mizzou-crawler-secrets" not found`
- [x] Compared with working CronWorkflow configuration
- [x] Verified CronWorkflow is working correctly
- [x] Identified old workflow structure (4-step vs 3-step)
- [x] Documented differences between correct and incorrect configs
- [x] Verified no old WorkflowTemplates exist
- [x] Searched codebase for submission scripts (none found)

### Pending ⏳

- [ ] Identify who/what is creating manual workflows
- [ ] Delete all failed manual workflows
- [ ] Stop currently running broken workflow
- [ ] Update documentation examples
- [ ] Create proper manual trigger guide
- [ ] Add monitoring for workflow submission patterns
- [ ] Consider RBAC restrictions or admission webhooks

---

## Monitoring

### Check for New Manual Workflows

```bash
# Watch for new manual workflow creation
kubectl get workflows -n production -w | grep manual

# Check last 10 manual workflows
kubectl get workflows -n production --sort-by=.metadata.creationTimestamp | grep manual | tail -10

# Check workflow creation rate
kubectl get workflows -n production -o json | \
  jq '.items[] | select(.metadata.generateName == "mizzou-news-pipeline-manual-") | .metadata.creationTimestamp' | \
  sort | uniq -c
```

### Alert on Failed Workflows

```bash
# Count failed workflows in last 24h
kubectl get workflows -n production -o json | \
  jq '[.items[] | select(.status.phase == "Failed" and .metadata.generateName == "mizzou-news-pipeline-manual-")] | length'
```

---

## Recommendations

### Short Term (Today)

1. **Delete broken workflows**: Stop wasting resources
2. **Find the source**: Check Argo UI access, search for automation
3. **Update docs**: Remove old manual trigger examples

### Medium Term (This Week)

4. **Create proper guide**: Document correct manual trigger method
5. **Add monitoring**: Alert on manual workflow submissions
6. **Restrict access**: Consider RBAC to limit who can submit workflows

### Long Term (Next Sprint)

7. **Admission webhook**: Enforce WorkflowTemplate-only submissions
8. **Self-service UI**: Create simple interface for triggering workflows with proper config
9. **Audit logging**: Track who submits what workflows

---

## Related Issues

- CronWorkflow: Working correctly (no action needed)
- WorkflowTemplate: Correct and up-to-date (no action needed)
- Manual submissions: Need to find source and prevent incorrect usage

---

## Questions

1. **Who has access to Argo UI?** Check authentication/authorization
2. **Is there external automation?** CI/CD, cron jobs, monitoring tools
3. **When did this start?** First manual workflow was 4 days ago - what changed?
4. **How many manual runs are expected?** Should manual triggers be disabled entirely?

---

**Next Step**: Run the investigation commands above to identify the source of manual workflow submissions.
