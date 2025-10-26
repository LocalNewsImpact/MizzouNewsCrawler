# PR #78 Rollout Plan - REVISED (After Infrastructure Review)

**Date**: October 15, 2025  
**PR**: #78 - Refactor orchestration: Split dataset jobs from continuous processor  
**Status**: REVISED after infrastructure review  

## Critical Findings from Infrastructure Review

### What I Learned

1. **No sidecar proxy**: System uses Cloud SQL Python Connector (direct in-app connection)
2. **Current processor behavior**: Processor is **actively running extraction** right now - logs show it extracting articles from multiple domains (fox4kc.com, www.darnews.com, etc.)
3. **Feature flags don't exist yet**: PR #78 **adds** these flags - they're not in current deployment
4. **Current deployment image**: `processor:d0c043e` (from k8s/processor-deployment.yaml)
5. **Database connectivity**: Works via DatabaseManager using Cloud SQL Python Connector (confirmed by API migration docs)

### What This Means for Deployment

**The PR #78 changes are NOT a simple flag flip - they're adding new code:**
- Adding feature flag environment variables (new code in continuous_processor.py)
- Adding conditional logic to skip disabled pipeline steps (new code)
- Adding new job templates for dataset-specific extraction
- **By default, the new flags disable external steps (discovery, verification, extraction)**

**This means deployment will IMMEDIATELY STOP extraction** unless we're careful.

---

## Revised Deployment Strategy

### Option A: Phased with Parallel Operation (RECOMMENDED)

Keep current extraction running while testing new jobs in parallel.

#### Phase 1: Deploy with Extraction Enabled (Safe Test)

**Goal**: Deploy PR #78 code but keep all steps enabled (backward compatible mode)

```yaml
# k8s/processor-deployment.yaml
env:
  - name: ENABLE_DISCOVERY
    value: "true"   # Keep enabled (default in PR is false!)
  - name: ENABLE_VERIFICATION
    value: "true"   # Keep enabled
  - name: ENABLE_EXTRACTION
    value: "true"   # Keep enabled  
  - name: ENABLE_CLEANING
    value: "true"
  - name: ENABLE_ML_ANALYSIS
    value: "true"
  - name: ENABLE_ENTITY_EXTRACTION
    value: "true"
```

**Validation**:
- Processor continues extraction as before
- Logs show "✅" for all pipeline steps
- No interruption to article flow

**Duration**: 24 hours monitoring

#### Phase 2: Test Mizzou Extraction Job (Parallel)

**Goal**: Run Mizzou extraction job alongside processor (both extracting)

1. Deploy mizzou-extraction-job.yaml
2. Monitor for conflicts (both trying to extract same articles)
3. Verify no rate limiting issues
4. Check for duplicate extractions

**Validation**:
- Both processor and job extract articles successfully
- No database conflicts
- Rate limiting works independently

**Duration**: 48 hours

#### Phase 3: Disable Processor Extraction (Cutover)

**Goal**: Switch Mizzou to job-only extraction

```yaml
# k8s/processor-deployment.yaml
env:
  - name: ENABLE_EXTRACTION
    value: "false"  # Disable in processor
```

**Validation**:
- Job continues extracting
- Processor continues cleaning/ML/entities
- No gaps in article flow

**Duration**: 48 hours

#### Phase 4: Full Migration

Repeat Phase 2-3 for other datasets.

**Total Duration**: 2-3 weeks

---

### Option B: Direct Cutover (HIGHER RISK)

Deploy PR #78 with extraction disabled immediately.

**Risks**:
- 2-day gap in article extraction while jobs are deployed
- Potential configuration issues discovered in production
- Rollback requires redeploying old image

**Only use if**:
- 2-day extraction pause is acceptable
- You have high confidence in PR #78 code
- Quick rollback capability is available

---

## Prerequisites (Must Complete Before Deployment)

### 1. Verify Current System State

```bash
# Check processor is running
kubectl get pods -n production -l app=mizzou-processor

# Verify it's extracting
kubectl logs -n production -l app=mizzou-processor --tail=200 | grep "extraction"

# Check current image
kubectl get deployment mizzou-processor -n production -o jsonpath='{.spec.template.spec.containers[0].image}'
```

### 2. Collect Baseline Metrics (WORKING APPROACH)

Use processor pod's database connection:

```bash
kubectl exec -n production deployment/mizzou-processor -- python -c "
from src.models.database import DatabaseManager
from sqlalchemy import text
db = DatabaseManager()
with db.get_session() as session:
    # Query 1: Article counts
    result = session.execute(text('SELECT status, COUNT(*) FROM articles GROUP BY status ORDER BY COUNT(*) DESC'))
    print('Article counts:')
    for row in result:
        print(f'  {row[0]}: {row[1]}')
    
    # Query 2: Extraction rate (24h)
    result = session.execute(text(\"SELECT COUNT(*) FROM articles WHERE created_at >= NOW() - INTERVAL '24 hours'\"))
    print(f'New articles (24h): {result.scalar()}')
    
    # Query 3: Queue depths
    result = session.execute(text(\"SELECT COUNT(*) FROM articles WHERE status = 'cleaning_pending'\"))
    cleaning = result.scalar()
    result = session.execute(text(\"SELECT COUNT(*) FROM articles WHERE status = 'analysis_pending'\"))
    analysis = result.scalar()
    print(f'Cleaning pending: {cleaning}')
    print(f'Analysis pending: {analysis}')
"
```

**Save this output** - you'll need it for comparison.

### 3. Review PR #78 Code Changes

**Must review**:
- `orchestration/continuous_processor.py` - feature flag logic
- `k8s/processor-deployment.yaml` - default flag values
- `tests/test_continuous_processor.py` - test coverage

**Key question**: Are the defaults in PR #78 correct for our deployment strategy?

---

## Deployment Commands (Option A - Phase 1)

### Step 1: Modify PR #78 Branch

**CRITICAL**: Before merging, update processor-deployment.yaml to keep extraction enabled:

```bash
git checkout copilot/refactor-pipeline-orchestration

# Edit k8s/processor-deployment.yaml
# Change ENABLE_EXTRACTION from "false" to "true"
# Change ENABLE_VERIFICATION from "false" to "true"  
# Change ENABLE_DISCOVERY from "false" to "true"

git add k8s/processor-deployment.yaml
git commit -m "Phase 1: Keep all pipeline steps enabled for backward compatibility"
git push
```

### Step 2: Merge and Deploy

```bash
# Merge to feature branch
git checkout feature/gcp-kubernetes-deployment
git merge copilot/refactor-pipeline-orchestration

# Run tests
python -m pytest tests/test_continuous_processor.py -v

# Build processor image
gcloud builds triggers run build-processor-manual \
  --branch=feature/gcp-kubernetes-deployment \
  --project=mizzou-news-crawler

# Wait for build to complete (get new image SHA)
# Then deploy
kubectl set image deployment/mizzou-processor \
  -n production \
  processor=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:<NEW_SHA>

# Watch rollout
kubectl rollout status deployment/mizzou-processor -n production

# Monitor logs
kubectl logs -n production -l app=mizzou-processor --follow
```

### Step 3: Validate (Phase 1)

**Check feature flags in logs**:
```
Enabled pipeline steps:
  - Discovery: ✅
  - Verification: ✅
  - Extraction: ✅
  - Cleaning: ✅
  - ML Analysis: ✅
  - Entity Extraction: ✅
```

**Verify extraction continues**:
```bash
kubectl logs -n production -l app=mizzou-processor --tail=500 | grep "articles extracted"
```

**Check database**:
- New articles should continue appearing in `articles` table
- Status transitions should work normally (discovered → article → extracted → cleaned)

---

## Rollback Procedures

### Immediate Rollback (< 2 minutes)

```bash
kubectl rollout undo deployment/mizzou-processor -n production
kubectl rollout status deployment/mizzou-processor -n production
```

### Rollback from Phase 3 (job-based extraction)

```bash
# Re-enable extraction in processor
kubectl set env deployment/mizzou-processor -n production \
  ENABLE_EXTRACTION=true \
  ENABLE_VERIFICATION=true

# Delete jobs
kubectl delete job mizzou-extraction -n production

# Verify processor resumes
kubectl logs -n production -l app=mizzou-processor --follow
```

---

## Success Criteria

### Phase 1 (Backward Compatible Deployment)
- ✅ Processor continues extracting articles
- ✅ All feature flags show ✅ in logs
- ✅ 32 tests passing
- ✅ 0 pod restarts
- ✅ New articles appearing in database at normal rate

### Phase 2 (Parallel Operation)
- ✅ Both processor and job extract articles
- ✅ No duplicate extractions
- ✅ Independent rate limiting works
- ✅ Database handles concurrent writes

### Phase 3 (Job-Only Extraction)
- ✅ Job extracts articles successfully
- ✅ Processor continues cleaning/ML/entities
- ✅ No gaps in article pipeline
- ✅ Queue depths remain healthy

---

## Risk Assessment (Revised)

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Extraction stops (wrong flags) | HIGH | CRITICAL | Phase 1: Keep all flags enabled |
| Database connection issues | LOW | HIGH | Already working (verified in logs) |
| Feature flag bugs | MEDIUM | HIGH | Tests cover flag logic (32 passing) |
| Concurrent extraction conflicts | MEDIUM | MEDIUM | Phase 2 parallel testing |
| CAPTCHA backoff confusion | LOW | MEDIUM | Jobs isolated by dataset |

---

## Timeline (Revised)

| Phase | Duration | Risk | Go/No-Go Decision |
|-------|----------|------|-------------------|
| Phase 1: Deploy with all flags enabled | 1 day | LOW | After 24h monitoring |
| Phase 2: Parallel Mizzou extraction | 2 days | MEDIUM | After successful parallel run |
| Phase 3: Disable processor extraction | 2 days | MEDIUM | After job proves stable |
| Phase 4: Migrate other datasets | 1-2 weeks | LOW | Per-dataset decisions |

**Total: 2-3 weeks** for full migration

---

## Lessons Learned

1. **Always review infrastructure first** - I assumed sidecar proxy, wasted time
2. **Check current behavior** - Processor is actively extracting, not idle
3. **Read PR changes carefully** - Feature flags are NEW code with specific defaults
4. **Test database connectivity** - Use existing working connections (kubectl exec)
5. **Plan for backward compatibility** - Don't break current functionality

---

## Next Steps

1. **You decide**: Option A (phased) or Option B (direct cutover)?
2. **If Option A**: I'll update PR #78 branch with backward-compatible flags
3. **Collect baseline metrics**: Run the kubectl exec command above
4. **Review PR #78 tests**: Verify 32 tests cover our deployment scenario
5. **Schedule deployment window**: When can we deploy Phase 1?

**Do you want to proceed with Option A (phased rollout)?**
