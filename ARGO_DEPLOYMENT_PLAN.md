# Argo Workflows Deployment Plan

## Overview

This document outlines the complete deployment plan for implementing Argo Workflows as described in Issue #79. The implementation is complete and ready for deployment.

## Implementation Status

### ✅ Completed

1. **RBAC Configuration** (`k8s/argo/rbac.yaml`)
   - ServiceAccount: `argo-workflow`
   - Role with required permissions
   - RoleBinding to attach role to service account

2. **Mizzou Pipeline Workflow** (`k8s/argo/mizzou-pipeline-workflow.yaml`)
   - CronWorkflow running every 6 hours at :00 (00:00, 06:00, 12:00, 18:00 UTC)
   - Three-step pipeline: Discovery → Verification → Extraction
   - Moderate rate limiting (5-15s between requests)
   - Automatic retry logic with exponential backoff

3. **Lehigh Pipeline Workflow** (`k8s/argo/lehigh-pipeline-workflow.yaml`)
   - CronWorkflow running every 6 hours at :30 (00:30, 06:30, 12:30, 18:30 UTC)
   - Offset schedule to avoid conflicts with Mizzou
   - Aggressive rate limiting (90-180s between requests) for Penn State bot protection
   - Automatic retry logic with longer backoff

4. **Deployment Scripts**
   - `scripts/deploy_argo_workflows.sh` - Automated deployment with dry-run support
   - `scripts/rollback_argo_workflows.sh` - Safe rollback mechanism

5. **Tests** (`tests/test_argo_workflows.py`)
   - 20 comprehensive tests validating all workflow configurations
   - YAML structure validation
   - Metadata and label verification
   - Environment variable checks
   - Rate limiting configuration validation

6. **Documentation** (`ARGO_WORKFLOWS_GUIDE.md`)
   - Complete installation guide
   - Usage instructions
   - Monitoring and troubleshooting
   - Rollback procedures

## Deployment Phases

### Phase 1: Pre-Deployment (Week 1, Days 1-2)

#### Prerequisites Check
- [ ] Verify kubectl access to GKE cluster
- [ ] Verify access to `production` namespace
- [ ] Verify existing CronJobs status
- [ ] Backup current CronJob configurations

#### Backup Commands
```bash
# Create backup directory
mkdir -p backup/cronjobs

# Backup existing CronJobs
kubectl get cronjob mizzou-discovery -n production -o yaml > backup/cronjobs/mizzou-discovery.yaml
kubectl get cronjob mizzou-processor -n production -o yaml > backup/cronjobs/mizzou-processor.yaml
kubectl get cronjob mizzou-crawler -n production -o yaml > backup/cronjobs/mizzou-crawler.yaml

# Backup deployment
kubectl get deployment mizzou-processor -n production -o yaml > backup/mizzou-processor-deployment.yaml
```

#### Validation
- [ ] Run dry-run deployment: `DRY_RUN=true ./scripts/deploy_argo_workflows.sh`
- [ ] Review generated resources
- [ ] Validate YAML syntax: `kubectl apply --dry-run=client -f k8s/argo/`

### Phase 2: Argo Installation (Week 1, Days 2-3)

#### Install Argo Workflows
```bash
# Install Argo Workflows in argo namespace
kubectl create namespace argo
kubectl apply -n argo -f https://github.com/argoproj/argo-workflows/releases/download/v3.5.0/install.yaml

# Wait for deployments
kubectl wait --for=condition=available --timeout=300s -n argo deployment/workflow-controller
kubectl wait --for=condition=available --timeout=300s -n argo deployment/argo-server

# Verify installation
kubectl get pods -n argo
```

#### Success Criteria
- [ ] workflow-controller pod running
- [ ] argo-server pod running
- [ ] No errors in pod logs

### Phase 3: RBAC and Workflow Deployment (Week 1, Day 3)

#### Deploy RBAC
```bash
# Deploy ServiceAccount, Role, and RoleBinding
kubectl apply -f k8s/argo/rbac.yaml

# Verify
kubectl get serviceaccount argo-workflow -n production
kubectl get role argo-workflow-role -n production
kubectl get rolebinding argo-workflow-binding -n production
```

#### Deploy Workflows (Initially Suspended)
```bash
# Deploy workflows in suspended state for testing
kubectl apply -f k8s/argo/mizzou-pipeline-workflow.yaml
kubectl apply -f k8s/argo/lehigh-pipeline-workflow.yaml

# Verify suspended
kubectl get cronworkflow -n production
```

#### Success Criteria
- [ ] RBAC resources created successfully
- [ ] CronWorkflows created
- [ ] Workflows show as suspended

### Phase 4: Testing (Week 1-2, Days 4-7)

#### Test 1: Manual Workflow Execution
```bash
# Trigger Mizzou workflow manually
argo submit --from cronwf/mizzou-news-pipeline -n production --name test-mizzou-1

# Watch execution
argo watch test-mizzou-1 -n production

# Check logs
argo logs test-mizzou-1 -n production

# Verify database
# - Check candidate_links table for discovered status
# - Check articles table for extracted status
```

**Success Criteria:**
- [ ] Discovery step completes successfully
- [ ] Verification step runs after discovery
- [ ] Extraction step runs after verification
- [ ] Database shows expected status transitions
- [ ] No rate limit violations

#### Test 2: Retry Logic
```bash
# Inject a temporary failure (e.g., wrong dataset name)
# Edit workflow to use non-existent dataset
# Submit workflow
# Verify automatic retry occurs
# Restore correct configuration
```

**Success Criteria:**
- [ ] Failed step retries automatically
- [ ] Exponential backoff works correctly
- [ ] Workflow eventually succeeds after fix

#### Test 3: Failure Handling
```bash
# Test discovery failure
# - Temporarily disable database access or use invalid credentials
# - Verify verification and extraction don't run
# - Check error messages in logs
```

**Success Criteria:**
- [ ] Failed discovery stops pipeline
- [ ] Clear error messages in logs
- [ ] No partial execution

#### Test 4: Lehigh Aggressive Rate Limiting
```bash
# Trigger Lehigh workflow
argo submit --from cronwf/lehigh-news-pipeline -n production --name test-lehigh-1

# Monitor timing between requests
# Verify 90-180 second delays
# Verify 7-minute batch sleep
```

**Success Criteria:**
- [ ] Rate limiting respected
- [ ] No CAPTCHA triggers
- [ ] Successful extraction

### Phase 5: Parallel Operation (Week 2, Days 1-3)

#### Suspend Old CronJobs
```bash
# Suspend old CronJobs (don't delete yet)
kubectl patch cronjob mizzou-discovery -n production -p '{"spec":{"suspend":true}}'
kubectl patch cronjob mizzou-processor -n production -p '{"spec":{"suspend":true}}'
kubectl patch cronjob mizzou-crawler -n production -p '{"spec":{"suspend":true}}'

# Verify suspended
kubectl get cronjobs -n production
```

#### Enable Argo Workflows
```bash
# Resume Mizzou workflow
kubectl patch cronworkflow mizzou-news-pipeline -n production -p '{"spec":{"suspend":false}}'

# Resume Lehigh workflow (after Mizzou runs successfully)
kubectl patch cronworkflow lehigh-news-pipeline -n production -p '{"spec":{"suspend":false}}'
```

#### Monitor
- [ ] Set up monitoring for next 48 hours
- [ ] Check workflow execution at each scheduled time
- [ ] Monitor database for article extraction rate
- [ ] Watch for any errors or failures

**Success Criteria (48-hour monitoring):**
- [ ] 8 Mizzou workflow runs completed successfully
- [ ] 8 Lehigh workflow runs completed successfully
- [ ] Extraction rate ≥ baseline (198 articles/24h for Mizzou)
- [ ] No rate limit violations
- [ ] No resource conflicts
- [ ] Processor continues handling cleaning/ML/entities

### Phase 6: Validation (Week 2-3, Days 4-7)

#### Metrics Collection
```bash
# Articles extracted per day
SELECT DATE(created_at), COUNT(*) 
FROM articles 
WHERE status = 'extracted' AND created_at > NOW() - INTERVAL '7 days'
GROUP BY DATE(created_at);

# Pipeline queue status
SELECT status, COUNT(*) FROM candidate_links GROUP BY status;

# Workflow success rate
kubectl get workflows -n production --sort-by=.status.finishedAt -o json | jq '.items[] | {name: .metadata.name, phase: .status.phase}'
```

#### Performance Comparison
- [ ] Compare extraction rate: Argo vs baseline
- [ ] Compare error rate: Argo vs baseline
- [ ] Compare resource usage
- [ ] Check for any regressions

**Success Criteria:**
- [ ] Extraction rate maintained or improved
- [ ] Error rate same or lower
- [ ] No new types of failures
- [ ] Clear visibility into pipeline status

### Phase 7: Cleanup (Week 3)

#### Delete Old CronJobs
```bash
# After successful 1-week validation period
kubectl delete cronjob mizzou-discovery -n production
kubectl delete cronjob mizzou-processor -n production
kubectl delete cronjob mizzou-crawler -n production

# Keep processor deployment for cleaning/ML/entities
# Ensure it has discovery/extraction disabled (already done in processor-deployment.yaml)
```

#### Update Documentation
- [ ] Update README.md with Argo workflows information
- [ ] Update ORCHESTRATION_ARCHITECTURE.md
- [ ] Add runbook for common operations
- [ ] Document troubleshooting procedures

#### Training
- [ ] Share Argo Workflows guide with team
- [ ] Demo Argo UI access and usage
- [ ] Review monitoring dashboards
- [ ] Explain rollback procedures

## Rollback Plan

### Immediate Rollback (If Critical Issues)

```bash
# 1. Suspend Argo workflows
kubectl patch cronworkflow mizzou-news-pipeline -n production -p '{"spec":{"suspend":true}}'
kubectl patch cronworkflow lehigh-news-pipeline -n production -p '{"spec":{"suspend":true}}'

# 2. Resume old CronJobs
kubectl patch cronjob mizzou-discovery -n production -p '{"spec":{"suspend":false}}'
kubectl patch cronjob mizzou-processor -n production -p '{"spec":{"suspend":false}}'
kubectl patch cronjob mizzou-crawler -n production -p '{"spec":{"suspend":false}}'

# 3. Scale up processor if needed
kubectl scale deployment mizzou-processor --replicas=1 -n production
```

### Full Rollback (If Persistent Issues)

```bash
# Use rollback script
./scripts/rollback_argo_workflows.sh

# Or manual steps:
# 1. Delete all running workflows
kubectl delete workflows -n production --all

# 2. Delete CronWorkflows
kubectl delete cronworkflow mizzou-news-pipeline lehigh-news-pipeline -n production

# 3. Delete RBAC resources
kubectl delete -f k8s/argo/rbac.yaml

# 4. Optional: Uninstall Argo
kubectl delete namespace argo
```

## Monitoring

### Key Metrics

1. **Workflow Execution Rate**
   - Mizzou: 4 runs per day
   - Lehigh: 4 runs per day

2. **Success Rate**
   - Target: >95% successful workflow completions

3. **Extraction Rate**
   - Baseline: 198 articles/24h (Mizzou)
   - Target: ≥ baseline

4. **Error Rate**
   - 403 bot blocks
   - CAPTCHA triggers
   - Retry counts

### Monitoring Commands

```bash
# Check workflow status
kubectl get workflows -n production -w

# Check CronWorkflow schedules
kubectl get cronworkflow -n production

# View recent logs
argo logs -n production -l workflows.argoproj.io/cron-workflow=mizzou-news-pipeline --tail=100

# Check resource usage
kubectl top pods -n production -l workflows.argoproj.io/workflow
```

### Alerts

Set up alerts for:
- [ ] Workflow failures (>2 consecutive failures)
- [ ] Long-running workflows (>2 hours)
- [ ] Resource exhaustion (CPU/memory limits)
- [ ] No workflows running for 12+ hours

## Success Criteria Summary

### Phase 1-2: Installation (Week 1)
- [ ] Argo Workflows installed successfully
- [ ] All pods running in argo namespace
- [ ] RBAC configured correctly
- [ ] Workflows deployed (suspended)

### Phase 3-4: Testing (Week 1-2)
- [ ] Manual workflow execution successful
- [ ] Retry logic working
- [ ] Failure handling correct
- [ ] Rate limiting respected

### Phase 5-6: Production (Week 2-3)
- [ ] 48-hour parallel operation successful
- [ ] Extraction rate ≥ baseline
- [ ] No rate limit violations
- [ ] No resource conflicts
- [ ] Clear pipeline visibility

### Phase 7: Finalization (Week 3)
- [ ] Old CronJobs deleted
- [ ] Documentation updated
- [ ] Team trained on Argo usage
- [ ] Monitoring dashboards configured

## Timeline

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| Pre-Deployment | 2 days | Backups, validation |
| Installation | 1 day | Argo installed, RBAC deployed |
| Testing | 4 days | Manual tests, validation |
| Parallel Operation | 3 days | Workflows running, monitoring |
| Validation | 4 days | Metrics collection, comparison |
| Cleanup | 3 days | Old CronJobs deleted, docs updated |
| **Total** | **~3 weeks** | **Complete migration** |

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Argo installation fails | High | Test in staging first, have rollback ready |
| Workflow timing conflicts | Medium | Offset schedules (Mizzou :00, Lehigh :30) |
| Rate limit violations | High | Keep same rate limits as before, monitor closely |
| Resource exhaustion | Medium | Set proper limits, monitor usage |
| Old CronJobs still running | Low | Suspend before enabling Argo |
| Lost visibility | Medium | Set up Argo UI access, monitoring |

## Support and Resources

### Documentation
- `ARGO_WORKFLOWS_GUIDE.md` - Complete usage guide
- `docs/ORCHESTRATION_ARCHITECTURE.md` - Architecture overview
- https://argoproj.github.io/argo-workflows/ - Official docs

### Commands Reference
```bash
# Access Argo UI
kubectl -n argo port-forward svc/argo-server 2746:2746
# Open https://localhost:2746

# List workflows
argo list -n production

# Watch workflow
argo watch <workflow-name> -n production

# View logs
argo logs <workflow-name> -n production

# Suspend/Resume CronWorkflow
kubectl patch cronworkflow <name> -n production -p '{"spec":{"suspend":true}}'
kubectl patch cronworkflow <name> -n production -p '{"spec":{"suspend":false}}'
```

## Contact

For issues or questions during deployment:
1. Check `ARGO_WORKFLOWS_GUIDE.md` troubleshooting section
2. Review Argo Workflows logs and events
3. Check this deployment plan for rollback procedures
4. Create GitHub issue with details if needed

## Sign-off

- [ ] Implementation complete (Developer)
- [ ] Tests passing (QA)
- [ ] Documentation reviewed (Tech Lead)
- [ ] Deployment approved (Product Owner)
- [ ] Production deployment complete (DevOps)
- [ ] Monitoring verified (DevOps)
- [ ] Team trained (Tech Lead)
