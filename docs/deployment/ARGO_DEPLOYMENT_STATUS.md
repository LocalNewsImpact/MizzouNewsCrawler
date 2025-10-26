# Argo Workflows Deployment Status

**Date**: October 15, 2025  
**Branch**: `copilot/apply-changes-from-issue-82` (PR #83)  
**Status**: ⚠️ **BLOCKED - Code Issue Found**

## ✅ Successfully Completed

### 1. Infrastructure Deployment
- ✅ Argo Workflows v3.5.5 installed in `argo` namespace
- ✅ Workflow controller and server running
- ✅ RBAC configuration deployed
- ✅ WorkflowTemplate (`news-pipeline-template`) deployed
- ✅ CronWorkflow (`mizzou-news-pipeline`) deployed
  - Schedule: Every 6 hours at :00 (00:00, 06:00, 12:00, 18:00 UTC)
  - Extract capacity: 50 articles/batch × 40 batches = 2,000 articles/run

### 2. Workload Identity Configuration
- ✅ ServiceAccount `argo-workflow` created in `production` namespace
- ✅ Workload Identity annotation added: `iam.gke.io/gcp-service-account=mizzou-k8s-sa@mizzou-news-crawler.iam.gserviceaccount.com`
- ✅ IAM binding created: `production/argo-workflow` → `mizzou-k8s-sa@mizzou-news-crawler.iam.gserviceaccount.com`
- ✅ Service Account Token Creator role granted
- ✅ Cloud SQL connection working ✓

### 3. Configuration Updates
- ✅ Extraction capacity increased from 1,200 → 2,000 articles/run
- ✅ RBAC YAML updated with Workload Identity annotation
- ✅ Deployment scripts tested and working

### 4. Argo UI Access
- ✅ Argo UI accessible at https://localhost:2746
- ✅ Namespace visibility configured
- ✅ ClusterRole for cross-namespace viewing created

## ❌ Blocking Issue Found

### SQL Syntax Error with pg8000 Driver

**Error**: `syntax error at or near ":" at position 711`

**Root Cause**: The `pg8000` database driver (used by Cloud SQL Python Connector) does not support SQLAlchemy's named parameter syntax (`:dataset_label`). It requires positional parameters (`%s`) or numeric placeholders.

**Location**: `src/crawler/discovery.py`, line 718
```python
df = pd.read_sql_query(query, db.engine, params=params or None)
```

**Affected Query**:
```sql
WHERE s.host IS NOT NULL AND s.host != '' AND d.label = :dataset_label
```

**Required Fix**:
1. Replace `:dataset_label` with `%(dataset_label)s` (pg8000 format)
2. OR: Use positional parameters: `?` or `%s`
3. OR: Switch to `psycopg2` driver (requires adding it to requirements.txt and Dockerfile)

**Files to Update**:
- `src/crawler/discovery.py` - Update named parameter syntax
- Possibly other files using `:param` syntax with pg8000

## 📊 Test Results

### Manual Workflow Test: `mizzou-pipeline-test-x4st9`
- **Status**: Failed at Discovery step
- **Pod**: Running and connected to Cloud SQL successfully
- **Error**: SQL syntax error (see above)
- **Duration**: ~5 seconds to failure
- **Logs**: Full traceback captured

### What Worked:
1. ✅ Workflow created and scheduled
2. ✅ Pod launched with correct ServiceAccount
3. ✅ Workload Identity authentication successful
4. ✅ Cloud SQL connection established
5. ✅ Cloud SQL Connector working
6. ✅ Database engine created

### What Failed:
1. ❌ SQL query execution due to pg8000 parameter syntax incompatibility

## 🔄 Next Steps

### Immediate (Code Fix Required)
1. **Fix SQL parameter syntax** in `src/crawler/discovery.py`
   - Option A: Convert `:param` → `%(param)s` for pg8000
   - Option B: Switch to `psycopg2` driver
   - Option C: Use paramstyle conversion in DatabaseManager

2. **Test locally** or in existing processor deployment first

3. **Rebuild processor image** with the fix

4. **Re-test Argo workflow** with new image

### After Code Fix
1. ✅ Verify Discovery step completes successfully
2. ✅ Verify Verification step runs
3. ✅ Verify Extraction step runs  
4. ✅ Check database for extracted articles
5. ✅ Suspend old CronJobs
6. ✅ Monitor 24-hour operation (4 scheduled runs)

## 💡 Recommendation

**This is a code compatibility issue, not a deployment issue.** The Argo Workflows deployment is complete and working correctly. The fix should be made in the application code (`src/crawler/discovery.py`) to ensure compatibility with the pg8000 driver used by Cloud SQL Python Connector.

**Quick Fix Strategy**:
```python
# Current (broken with pg8000):
query = "... WHERE d.label = :dataset_label ..."
params = {'dataset_label': 'Mizzou'}

# Fixed for pg8000:
query = "... WHERE d.label = %(dataset_label)s ..."
params = {'dataset_label': 'Mizzou'}
```

## 📝 Files Modified in PR #83

1. `k8s/argo/base-pipeline-workflow.yaml` - Base workflow template
2. `k8s/argo/mizzou-pipeline-cronworkflow.yaml` - Mizzou CronWorkflow (capacity: 2,000/run)
3. `k8s/argo/dataset-pipeline-template.yaml` - Template for new datasets
4. `k8s/argo/rbac.yaml` - RBAC with Workload Identity annotation
5. `k8s/argo/README.md` - Documentation
6. `scripts/deploy_argo_workflows.sh` - Deployment automation
7. `scripts/rollback_argo_workflows.sh` - Rollback automation
8. `tests/test_argo_workflows.py` - 30+ tests for Argo configuration
9. `docs/ARGO_SETUP.md` - Setup guide
10. `docs/ARGO_DEPLOYMENT_PLAN.md` - Deployment plan
11. `ARGO_EXTRACTION_CAPACITY_UPDATE.md` - Capacity planning doc
12. `ARGO_DEPLOYMENT_STATUS.md` - This file

## 🎯 Success Criteria (Pending Code Fix)

Once the SQL syntax is fixed:

**Phase 4: Initial Test**
- [ ] Discovery finds URLs from 50 sources
- [ ] Verification validates reachable URLs
- [ ] Extraction extracts content
- [ ] Database shows articles in 'extracted' status
- [ ] No rate limit violations

**Phase 5: 24-Hour Validation**
- [ ] 4 successful workflow runs (every 6 hours)
- [ ] ~160-200 articles extracted per day
- [ ] <1% failure rate
- [ ] No resource conflicts
- [ ] Processor keeps up with cleaning/ML/entities

## 🔧 IAM Configuration (Completed)

```bash
# Workload Identity binding
serviceAccount:mizzou-news-crawler.svc.id.goog[production/argo-workflow]
  → mizzou-k8s-sa@mizzou-news-crawler.iam.gserviceaccount.com

# Roles granted
- roles/iam.workloadIdentityUser
- roles/iam.serviceAccountTokenCreator
- roles/cloudsql.client (inherited from mizzou-k8s-sa)
```

## 📞 Contact

For questions about the Argo deployment: See Issue #82 and PR #83  
For the SQL syntax fix: Create a separate issue or PR for code compatibility
