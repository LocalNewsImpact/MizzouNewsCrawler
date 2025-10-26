# Production Deployment Checklist - Before Merging to Main

**Current Status**: Feature branch has 514 commits ahead of main with significant infrastructure changes.

## 🚨 Critical Considerations

### Why Deploy Before Merging:

1. **Infrastructure Migration** - This is a major GCP/Kubernetes deployment
   - Feature branch: GCP Cloud SQL + Kubernetes
   - Main branch: Legacy infrastructure
   - Risk: High if merged without validation

2. **Recent Changes** - Just fixed 14 critical issues including:
   - ✅ RSS metadata persistence bug (production-critical)
   - ✅ ORM schema synchronization with Cloud SQL
   - ✅ 1260 tests passing with 80.76% coverage
   - ⚠️ Changes not yet validated in production environment

3. **Scale of Changes** - 514 commits difference
   - Too large to merge without production validation
   - Need real-world traffic patterns to verify
   - Monitor for edge cases tests might miss

## ✅ Recommended Deployment Strategy

### Phase 1: Wait for CI to Pass (In Progress)
```bash
# Monitor CI status on GitHub
# https://github.com/LocalNewsImpact/MizzouNewsCrawler/actions
```
- ⏳ CI running after your push (commit 3fe42ce)
- ✅ All static checks should pass (ruff, black, isort, mypy)
- ✅ All 1260 tests should pass
- ✅ Coverage should meet 80% threshold

### Phase 2: Deploy to Production (Recommended)
```bash
# Option A: Deploy all services
make -f Makefile deploy-all-services  # if available

# Option B: Deploy incrementally
./scripts/deploy-processor.sh
./scripts/deploy-api.sh
./scripts/deploy-crawler.sh

# Option C: Use Cloud Build triggers
gcloud builds triggers run build-processor-manual --branch=feature/gcp-kubernetes-deployment
gcloud builds triggers run build-api-manual --branch=feature/gcp-kubernetes-deployment
gcloud builds triggers run build-crawler-manual --branch=feature/gcp-kubernetes-deployment
```

### Phase 3: Monitor Production (24-48 hours)

**Critical Metrics to Watch:**
- [ ] RSS feed discovery success rate
- [ ] Article extraction success rate  
- [ ] Database query performance
- [ ] Telemetry data collection
- [ ] Error rates in Cloud Logging
- [ ] Memory/CPU usage in GKE pods

**Specific Checks for Recent Fixes:**
- [ ] RSS metadata being persisted correctly
- [ ] Scheduling cadence working with 12-hour windows
- [ ] Entity extraction with gazetteer OR logic
- [ ] No ORM schema mismatch errors
- [ ] http_error_summary UNIQUE constraint working
- [ ] Telemetry tables accepting all expected columns

**Where to Monitor:**
```bash
# Check pod logs
kubectl logs -n production -l app=processor --tail=100 -f
kubectl logs -n production -l app=api --tail=100 -f
kubectl logs -n production -l app=crawler --tail=100 -f

# Check Cloud SQL queries
# (Cloud Console → Cloud SQL → Query Insights)

# Check error rates
# (Cloud Console → Logging → Error Reporting)
```

### Phase 4: Merge to Main (After Production Validation)

**Only proceed if:**
- ✅ CI passes on feature branch
- ✅ Production deployment successful
- ✅ 24-48 hours of stable operation
- ✅ No critical errors in monitoring
- ✅ RSS metadata fix confirmed working
- ✅ ORM schema changes validated with real traffic

**Merge Steps:**
```bash
# 1. Ensure feature branch is up to date
git checkout feature/gcp-kubernetes-deployment
git pull origin feature/gcp-kubernetes-deployment

# 2. Create PR or direct merge (depending on team workflow)
# Option A: Via PR (recommended for audit trail)
gh pr create --base main --head feature/gcp-kubernetes-deployment \
  --title "Merge GCP Kubernetes deployment to main" \
  --body "Production validated for 48 hours. All systems stable."

# Option B: Direct merge (if no PR workflow)
git checkout main
git pull origin main
git merge feature/gcp-kubernetes-deployment
git push origin main
```

## 🎯 Current Action Items

### Immediate (Next 1 hour):
1. ⏳ Wait for CI to complete on commit 3fe42ce
2. ✅ Review CI results when ready
3. 📝 Plan deployment window

### Short-term (Next 24 hours):
1. 🚀 Deploy to production from feature branch
2. 👀 Monitor initial deployment (first 2-4 hours closely)
3. 📊 Review telemetry and error logs

### Before Merge (24-48 hours):
1. ✅ Confirm all monitoring looks good
2. ✅ Validate RSS metadata fix in production
3. ✅ Verify ORM schema changes stable
4. 📝 Document any issues found
5. 🔀 Merge to main

## 🚫 What NOT to Do

- ❌ Don't merge to main before production validation
- ❌ Don't skip the monitoring phase
- ❌ Don't deploy all services at once without staged rollout
- ❌ Don't ignore warnings in logs even if "everything works"
- ❌ Don't rush the merge - 514 commits need validation

## 📞 Rollback Plan

If issues are found in production:

```bash
# Revert to previous deployment
kubectl rollout undo deployment/processor -n production
kubectl rollout undo deployment/api -n production
kubectl rollout undo deployment/crawler -n production

# Or rollback to specific revision
kubectl rollout history deployment/processor -n production
kubectl rollout undo deployment/processor --to-revision=N -n production
```

## 📚 References

- CI Status: https://github.com/LocalNewsImpact/MizzouNewsCrawler/actions
- Deployment docs: docs/DEPLOYMENT_BEST_PRACTICES.md
- Cloud Build: cloudbuild-processor.yaml, cloudbuild-api.yaml
- K8s configs: k8s/*.yaml

---

**TL;DR**: Deploy to production first, monitor for 24-48 hours, THEN merge to main. The feature branch is too large and has too many critical fixes to merge without production validation.
