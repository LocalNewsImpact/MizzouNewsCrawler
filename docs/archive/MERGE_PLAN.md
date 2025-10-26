# Merge Plan: Option A - Test Current Fixes First

**Date**: October 14, 2025  
**Decision**: Proceed with Option A - merge our battle-tested fixes first

## Current Status

### Active Branch: `feature/gcp-kubernetes-deployment`

**Commits Ready for Testing:**
1. **15c831f**: Article count display (query after each batch)
2. **98d2733**: Article count accuracy (session cleanup)
3. **6bd5ca9**: Single-domain batch sleep detection
4. **8276768**: Dataset-filtered count query ⭐ **CRITICAL FIX**
5. **7b9e9a5**: False positive single-domain detection (rate-limited domains) ⭐ **CRITICAL FIX**
6. **9b2e035**: Documentation
7. **615f8f9**: Fix 404/410 fallback to BS/Selenium ⭐ **CRITICAL FIX**
8. **c59124a**: Fix ALL HTTP error codes triggering fallback ⭐ **CRITICAL FIX**

### Lehigh Job Status

- **Current Image**: processor:6bd5ca9 (OLD - missing commits 8276768, 7b9e9a5, 615f8f9, c59124a)
- **Running**: 158+ minutes, Batch 17 complete
- **Actual Remaining**: 61 articles (database query)
- **Logs Show**: 172 remaining ❌ (proves count query fix needed)
- **Estimated Completion**: 2-3 hours

### Open PRs to Address
- **PR #75** (Draft): Smart single-domain detection - REDUNDANT with our fixes
- **PR #76** (Ready): Infrastructure (config, Docker, telemetry) - INDEPENDENT

---

## Execution Plan

### Phase 1: Test Current Fixes ✅ (In Progress)

#### 1.1 Wait for Lehigh Job Completion
- [x] Job running with OLD image (processor:6bd5ca9)
- [ ] Wait for job to complete or stop (~2-3 hours)
- [ ] Verify final completion status

#### 1.2 Rebuild Processor with Latest Fixes
```bash
# Trigger Cloud Build with commits 8276768, 7b9e9a5, 9b2e035
gcloud builds triggers run build-processor-manual --branch=feature/gcp-kubernetes-deployment
```

**Expected Image**: `processor:c59124a` (or `processor:latest` with same commit)

#### 1.3 Verify Deployment
```bash
# Check image was updated
kubectl get deployment mizzou-processor -n production -o jsonpath='{.spec.template.spec.containers[0].image}'

# Verify rollout completed
kubectl rollout status deployment/mizzou-processor -n production
```

#### 1.4 Restart Lehigh Job with New Image
```bash
# Delete completed job
kubectl delete job lehigh-extraction -n production

# Update job YAML to new image
# Edit k8s/lehigh-extraction-job.yaml line 18: processor:c59124a

# Apply updated job
kubectl apply -f k8s/lehigh-extraction-job.yaml

# Monitor new job
kubectl logs -f -n production $(kubectl get pods -n production -l app=lehigh-extraction -o jsonpath='{.items[0].metadata.name}')
```

### Phase 2: Validate Fixes ✅

#### 2.1 Test Dataset-Filtered Count Query (Commit 8276768)
**Expected Behavior:**
- Logs should show accurate remaining count for Lehigh dataset
- Should match database query: ~61 articles
- NOT show count across all datasets (172+)

**Validation:**
```bash
# Watch logs for "Batch X complete: Y articles extracted (Z remaining)"
kubectl logs -f -n production <lehigh-pod> | grep "complete:"

# Compare with database query
kubectl exec -n production deployment/mizzou-api -- python -c "..."
```

**Success Criteria:** ✅ Log count matches database count (±3 articles for batch processing)

#### 2.2 Test False Single-Domain Detection Fix (Commit 7b9e9a5)
**Expected Behavior:**
- Lehigh (true single-domain): "⏸️ Single-domain dataset - waiting Xs..."
- Multi-domain processor with rate-limited domains: "✓ Multiple domains available (X rate-limited) - minimal 5s pause"

**Validation:**
```bash
# Check Lehigh job logs
kubectl logs -n production <lehigh-pod> | grep -E "(Single-domain|Multiple domains)"

# Check mizzou-processor logs (general multi-domain processing)
kubectl logs -n production deployment/mizzou-processor | grep -E "(Single-domain|Multiple domains)"
```

**Success Criteria:**
- ✅ Lehigh shows "Single-domain dataset" (skipped_domains = 0)
- ✅ Multi-domain shows "Multiple domains available (X rate-limited)" when domains skipped

#### 2.3 Test Session Cleanup (Commits 98d2733)
**Expected Behavior:**
- Count queries return fresh data (not stale cached values)
- Remaining count decreases predictably batch-by-batch

**Success Criteria:** ✅ No stale counts observed over multiple batches

### Phase 3: Close Redundant PR #75 ❌

**Rationale:**
- PR #75 implements proactive domain analysis (`_analyze_dataset_domains()`)
- Our reactive approach (commits 6bd5ca9, 7b9e9a5) solves the same problem more simply
- Our solution is already tested and working
- Proactive analysis adds complexity without clear benefit

**Actions:**
```bash
# Add closing comment to PR #75
# Explain that commits 6bd5ca9 and 7b9e9a5 solve the problem more elegantly
# Thank Copilot for the alternative approach
# Close PR as "Not needed - solved differently"
```

### Phase 4: Review & Merge PR #76 ✅

**PR #76 Focus**: Infrastructure improvements (independent of extraction logic)
- Config management (`src/config.py`, `create_engine_from_env()`)
- Unit tests (`tests/test_config_db_layering.py`, `tests/test_telemetry_integration.py`)
- Docker Compose setup
- Telemetry integration

**Review Checklist:**
- [ ] No conflicts with `feature/gcp-kubernetes-deployment` branch
- [ ] Unit tests pass locally
- [ ] `create_engine_from_env()` works correctly
- [ ] Docker Compose setup doesn't break existing workflows
- [ ] Telemetry integration doesn't break existing commands
- [ ] Documentation is clear and complete

**Testing:**
```bash
# Fetch PR #76 branch
git fetch origin copilot/develop-phases-1-5-pr-75:pr-76-review
git checkout pr-76-review

# Run new tests
pytest tests/test_config_db_layering.py -v
pytest tests/test_telemetry_integration.py -v

# Verify imports work
python -c "from src.models import create_engine_from_env; print(create_engine_from_env())"

# Check Docker Compose
docker-compose config  # Validate YAML
```

**Merge Strategy:**
```bash
# If tests pass, merge PR #76 into feature branch
git checkout feature/gcp-kubernetes-deployment
git merge pr-76-review --no-ff -m "Merge PR #76: Infrastructure improvements (config, tests, Docker)"

# Push merged changes
git push origin feature/gcp-kubernetes-deployment
```

### Phase 5: Merge to Main 🎯

**Prerequisites:**
- ✅ All fixes tested in production (Lehigh job)
- ✅ PR #75 closed
- ✅ PR #76 merged (if applicable)
- ✅ No outstanding issues

**Actions:**
```bash
# Create PR: feature/gcp-kubernetes-deployment → main
# Title: "Production-tested extraction fixes: count accuracy, single-domain detection, rate limiting"
# Body: Include summary of all commits, test results, deployment verification

# After approval, merge to main
git checkout main
git pull origin main
git merge feature/gcp-kubernetes-deployment --no-ff
git push origin main
```

---

## Testing Checklist

### Critical Tests (Must Pass)

#### Lehigh Job (Single-Domain Dataset)
- [ ] Accurate remaining count (matches database query)
- [ ] 7-minute pauses between batches ("Single-domain dataset - waiting Xs...")
- [ ] No false positives (doesn't trigger when it shouldn't)
- [ ] Completes successfully (processes all remaining 61 articles)

#### Multi-Domain Processor (mizzou-processor)
- [ ] Short pause (5s) when domains are rate-limited ("Multiple domains available (X rate-limited)")
- [ ] Long pause (420s) only when truly single-domain (skipped_domains = 0)
- [ ] No unnecessary delays in multi-domain scenarios

#### Count Accuracy
- [ ] Dataset-filtered queries return correct counts
- [ ] Session cleanup prevents stale cached data
- [ ] Counts match database queries throughout extraction

### Nice-to-Have Tests

- [ ] PR #76 infrastructure changes don't break existing code
- [ ] Docker Compose setup works correctly
- [ ] Telemetry integration provides useful metrics
- [ ] Documentation is clear and complete

---

## Success Metrics

### Performance
- **Count Accuracy**: ±3 articles difference between logs and database
- **Pause Correctness**: Single-domain applies 7-min pause 100% of batches
- **No False Positives**: Multi-domain never applies long pause when domains are just rate-limited

### Operational
- **Lehigh Completion**: Processes all 61 remaining articles successfully
- **No Manual Intervention**: Job completes without operator assistance
- **Clear Logs**: Operators understand why pauses are happening

### Code Quality
- **Backward Compatible**: Existing jobs work unchanged
- **Well Documented**: SINGLE_DOMAIN_DETECTION_FIX.md explains all changes
- **Tested**: Unit tests cover edge cases

---

## Rollback Plan

If any tests fail:

### Rollback Deployment
```bash
# Revert to previous working image
kubectl set image deployment/mizzou-processor processor=processor:6bd5ca9 -n production

# Verify rollback
kubectl rollout status deployment/mizzou-processor -n production
```

### Rollback Code
```bash
# Revert commits if needed
git checkout feature/gcp-kubernetes-deployment
git revert <commit-sha>
git push origin feature/gcp-kubernetes-deployment
```

### Restart Lehigh Job with Old Config
```bash
# Use old job YAML
kubectl delete job lehigh-extraction -n production
kubectl apply -f k8s/lehigh-extraction-job-backup.yaml
```

---

## Timeline

- **Current**: Lehigh job running with OLD image (processor:6bd5ca9)
- **+2-3 hours**: Lehigh job completes
- **+3 hours**: Rebuild with new image (9b2e035)
- **+3.5 hours**: Restart Lehigh job for testing
- **+5-6 hours**: Verify fixes work correctly
- **+6 hours**: Close PR #75, review PR #76
- **+7 hours**: Merge to main (if all tests pass)

**Total Time**: ~7 hours from now

---

## Next Actions (Immediate)

1. ⏳ **Wait** for current Lehigh job to complete (~2-3 hours)
2. 🔨 **Build** new processor image with commits 8276768, 7b9e9a5, 9b2e035
3. 🚀 **Deploy** new image to production
4. 🧪 **Test** fixes with restarted Lehigh job
5. ✅ **Validate** all success criteria met
6. 🎯 **Merge** to main

---

## Contact

For questions or issues during execution:
- Check logs: `kubectl logs -f -n production <pod>`
- Query database: `kubectl exec -n production deployment/mizzou-api -- python -c "..."`
- Monitor job: `kubectl get job lehigh-extraction -n production`

---

**Status**: ⏳ Waiting for Lehigh job completion  
**Next Update**: When job completes or in 2 hours (whichever comes first)
