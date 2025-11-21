# Selective Build System - Deployment Checklist

This document is your guide for successfully deploying and validating the selective build system.

## Pre-Deployment (Now)

- [x] Created `.github/workflows/selective-service-build.yml` workflow file
- [x] Created service detection documentation (`docs/SELECTIVE_BUILD_MAPPING.md`)
- [x] Created CI/CD architecture documentation (`docs/CI_CD_SERVICE_DETECTION.md`)
- [x] Created testing scripts (`scripts/test-selective-build.sh`, `scripts/simulate-selective-build.sh`)
- [x] Created testing guide (`docs/SELECTIVE_BUILD_TESTING.md`)
- [x] Validated detection logic locally (tested against current branch)

## Phase 1: Initial Main Branch Push (First Test)

### Objective
Get the selective build workflow running on the first main push to validate it works.

**Timeline**: Immediately after PR merge to main

### Steps

1. **Merge `fix/add-daily-housekeeping` to main**
   - [ ] Create pull request
   - [ ] Request review (approval required)
   - [ ] Merge to main (squash or merge commit)

2. **Watch GitHub Actions Workflow**
   - [ ] Go to GitHub → Actions
   - [ ] Find `selective-service-build` workflow run
   - [ ] Click to view detailed job logs

3. **Verify `detect-changes` Job**
   - [ ] Check job output in GitHub Actions
   - [ ] Confirm git diff is detected correctly
   - [ ] Verify service detection outputs (rebuild-base, rebuild-ml-base, etc.)
   - [ ] Expected result: Multiple services should rebuild (base changed due to alembic files)

4. **Monitor Service Build Jobs**
   - [ ] Watch each service build job execute
   - [ ] Verify correct dependencies (base before ml-base, etc.)
   - [ ] Check job logs for gcloud trigger execution:
     ```
     gcloud builds triggers run base-manual --branch=main
     gcloud builds triggers run ml-base-manual --branch=main
     gcloud builds triggers run migrator-manual --branch=main
     ...
     ```

5. **Verify Cloud Build Integration**
   - [ ] Go to GCP Console → Cloud Build → History
   - [ ] Confirm builds triggered in correct order
   - [ ] Check build completion status (success/failure)
   - [ ] Verify correct image tags in Artifact Registry

6. **Validate Cloud Deploy Release**
   - [ ] Go to GCP Console → Cloud Deploy → Releases
   - [ ] Check for new release created with affected services
   - [ ] Verify delivery pipeline execution to GKE
   - [ ] Monitor Argo Workflow for pod updates

7. **Check GKE Deployment Updates**
   - [ ] Verify pod rollouts in production namespace
   - [ ] Check image SHAs match Artifact Registry
   - [ ] Monitor for any deployment issues

8. **Document Results**
   - [ ] Record which services were detected as changed
   - [ ] Note build times for each service
   - [ ] Document any issues or unexpected behavior
   - [ ] Save screenshots of GitHub Actions summary

## Phase 2: Validation with Real Scenarios (Week 1)

### Objective
Test the selective build system with realistic commit patterns and verify it behaves correctly for different scenarios.

**Timeline**: Days 1-7 after merge to main

### Scenario 1: Crawler-Only Fix
**What**: Push a fix to src/crawler/

**Steps**:
- [ ] Create branch and make crawler-only changes
- [ ] Run local test before pushing: `./scripts/test-selective-build.sh`
- [ ] Verify detection shows: base, migrator, crawler (NOT processor, NOT api, NOT ml-base)
- [ ] Push to main and create PR
- [ ] After merge, watch GitHub Actions
- [ ] Confirm only expected services rebuild
- [ ] Validate build times (should be ~15-20 min instead of ~40 min full rebuild)

**Expected Detection**:
```
✅ CRAWLER - Discovery/verification/extraction changes detected
✅ BASE - Base image changes detected (src/crawler/ detected)
🔗 BASE changed → rebuilding all dependent services
```

⚠️ **Note**: The BASE pattern is broad and includes all src/ files. If only src/crawler/ changes, it will still trigger full rebuild. This is by design (safer defaults).

### Scenario 2: Database Migration
**What**: Push only alembic migration files

**Steps**:
- [ ] Create branch with only alembic/versions/ changes
- [ ] Run local test: `./scripts/test-selective-build.sh`
- [ ] Verify detection shows: migrator ONLY
- [ ] Expected output: "Building 1 service(s)"
- [ ] Push and validate GitHub Actions
- [ ] Check that no image rebuilds happen (only migrations run)
- [ ] Verify Cloud Deploy handles migration-only release

### Scenario 3: Documentation Update
**What**: Update README.md and docs/*.md files

**Steps**:
- [ ] Create branch with doc changes only
- [ ] Run local test: `./scripts/test-selective-build.sh`
- [ ] Verify detection shows: migrator only (no service image changes)
- [ ] Push and validate
- [ ] Expected: ~2 minute build time (just migrator schema validation)

### Scenario 4: ML Feature Addition
**What**: Add code to src/ml/ or src/cli/commands/analysis.py

**Steps**:
- [ ] Create branch with ML changes
- [ ] Run local test: `./scripts/test-selective-build.sh`
- [ ] Verify detection shows: base, migrator, processor (not api, not crawler)
- [ ] Push and validate
- [ ] Confirm processor rebuilds with new ML code

### Scenario 5: API Change
**What**: Update backend/ routes or API code

**Steps**:
- [ ] Create branch with API changes
- [ ] Run local test: `./scripts/test-selective-build.sh`
- [ ] Verify detection shows: base, migrator, api (not processor, not crawler)
- [ ] Push and validate
- [ ] Confirm api service rebuilds only

## Phase 3: Pattern Refinement (Week 2)

### Objective
Fine-tune file patterns based on real-world usage and team feedback.

**Timeline**: Days 8-14 after deployment

### Review Pattern Accuracy
- [ ] Analyze GitHub Actions logs for false positives
  - Files that triggered services unnecessarily
  - Suggest pattern adjustments
- [ ] Check for false negatives
  - Files that should have triggered a service but didn't
  - Suggest pattern expansions
- [ ] Collect metrics:
  - Average build times per service
  - Build time savings vs old all-or-nothing system
  - Number of skipped services per push

### Update Patterns If Needed
- [ ] Modify patterns in `.github/workflows/selective-service-build.yml`
- [ ] Add new patterns for newly discovered edge cases
- [ ] Update documentation (`SELECTIVE_BUILD_MAPPING.md`) with rationale

### Update Service Detection Rules
- [ ] Adjust BASE pattern to be more specific if needed
  - Currently includes all `src/` changes
  - Could be narrowed to just `src/config.py` if specific enough
- [ ] Add new service patterns for features added post-deployment
- [ ] Document any complex pattern decisions

## Phase 4: Optimization (Ongoing)

### Objective
Continuously optimize build times and accuracy.

### Monthly Reviews
- [ ] Analyze build execution patterns
- [ ] Identify frequently rebuilt services
- [ ] Look for opportunities to optimize dependencies
- [ ] Review team feedback on build accuracy

### Performance Metrics to Track
- [ ] Average build time per service type
- [ ] Percentage of service-skipping by scenario
- [ ] Build success rate
- [ ] Time saved vs old system
- [ ] Cloud Build cost reduction

### Documentation Updates
- [ ] Keep `SELECTIVE_BUILD_MAPPING.md` current with new patterns
- [ ] Update examples as new scenarios emerge
- [ ] Document any special cases discovered
- [ ] Maintain troubleshooting guide with lessons learned

## Rollback Plan

If issues occur, the system can be safely rolled back:

### Option 1: Disable Workflow (Quick)
```bash
# In .github/workflows/selective-service-build.yml:
# Comment out the trigger event or change to 'never'
```

### Option 2: Revert to All Services
```bash
# In detect-changes job, set all outputs to 'true':
rebuild-base: 'true'
rebuild-ml-base: 'true'
rebuild-migrator: 'true'
rebuild-processor: 'true'
rebuild-api: 'true'
rebuild-crawler: 'true'
```

### Option 3: Manual Trigger
```bash
# Trigger full rebuild manually via gcloud:
gcloud builds triggers run deploy-services --branch=main
```

## Success Criteria

The selective build system is considered successfully deployed when:

- [ ] **Accuracy**: Detection correctly identifies affected services in 95%+ of commits
- [ ] **Performance**: Build times reduced by 30-50% for typical single-service changes
- [ ] **Reliability**: 99%+ successful workflow execution (no spurious failures)
- [ ] **Visibility**: GitHub Actions summary clearly shows which services will rebuild
- [ ] **Documentation**: All team members understand service detection patterns
- [ ] **Team Adoption**: Team uses it without issues for 2+ weeks

## Communication

### Before Deployment
- [ ] Notify team: "Selective build system deploying with next main merge"
- [ ] Share this checklist
- [ ] Share testing guide: `docs/SELECTIVE_BUILD_TESTING.md`

### After Deployment
- [ ] Announce successful first deploy
- [ ] Share results: "X services built in Y minutes (was Z minutes)"
- [ ] Provide debugging guide for unexpected behavior
- [ ] Set up feedback channel for pattern suggestions

### Ongoing
- [ ] Monthly update on build times and cost savings
- [ ] Quarterly review of file patterns and accuracy
- [ ] Annual assessment of system effectiveness

## Important Reminders

⚠️ **Critical Points**:

1. **The workflow runs on EVERY main push**
   - It will automatically detect changes and trigger builds
   - This is the desired behavior
   - No manual intervention needed for normal operation

2. **Cloud Build Triggers are still configured to all activate on main**
   - The workflow is an additional layer on top
   - If workflow doesn't trigger a service, the old trigger still would
   - This provides safety but no cost benefit for skipped services

3. **Migrator ALWAYS rebuilds on main**
   - This is intentional for database safety
   - Even docs-only changes will trigger migrator
   - This ensures schema consistency across deployments

4. **BASE is a foundational dependency**
   - If BASE changes, ALL services rebuild
   - Currently BASE includes all src/ files (broad pattern)
   - This provides safety at the cost of some missed optimizations

5. **Dependencies are NOT enforced in Cloud Build**
   - The workflow uses `needs` to order execution
   - But gcloud triggers fire independently
   - Build order is enforced by workflow job dependencies, not Cloud Build

## Next Steps

1. **Immediate**: Prepare PR for housekeeping feature merge
2. **Day 0**: Merge to main and watch first workflow execution
3. **Week 1**: Run validation scenarios 1-5
4. **Week 2**: Review patterns and refine if needed
5. **Ongoing**: Monitor build metrics and optimize

---

**Questions or Issues?**

Refer to:
- Testing guide: `docs/SELECTIVE_BUILD_TESTING.md`
- Service mapping: `docs/SELECTIVE_BUILD_MAPPING.md`
- CI/CD architecture: `docs/CI_CD_SERVICE_DETECTION.md`
