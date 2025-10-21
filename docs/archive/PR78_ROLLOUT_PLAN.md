# PR #78 Orchestration Refactor - Phased Rollout Plan

**Created**: October 15, 2025  
**PR**: #78 - Refactor orchestration: Split dataset jobs from continuous processor  
**Related Issue**: #77  
**Branch**: `copilot/refactor-pipeline-orchestration`  
**Target**: `feature/gcp-kubernetes-deployment`

---

## Executive Summary

PR #78 refactors the pipeline orchestration to separate external site interaction (discovery/extraction) from internal processing (cleaning/ML/entities). This enables:

- **Independent rate limiting** per dataset (Lehigh 90-180s, Mizzou 5-15s)
- **Isolated CAPTCHA backoff** (blocks on one dataset don't affect others)
- **Better monitoring** with per-dataset Kubernetes labels
- **Easy scaling** by copying job templates
- **Resource efficiency** (ML models loaded once, shared across all datasets)

**Timeline**: 3-4 weeks for complete rollout  
**Risk Level**: Low (non-breaking, gradual migration with rollback procedures)

---

## Pre-Deployment Checklist

### 1. Review and Testing ✅
- [x] All 32 continuous processor tests passing
- [x] PR documentation complete (395 lines architecture, 441 lines migration guide)
- [x] Templates created for discovery and extraction jobs
- [x] Feature flags implemented and tested
- [ ] **Action Required**: Review PR #78 code changes
- [ ] **Action Required**: Validate test coverage for new feature flags

### 2. Infrastructure Readiness
- [ ] **Action Required**: Verify processor image built and pushed to Artifact Registry
- [ ] **Action Required**: Confirm Kubernetes cluster has sufficient resources:
  - Current processor: 1 CPU, 3Gi memory
  - Per dataset job: 0.5-1 CPU, 1-2Gi memory
  - Total estimate: 2-3 CPUs, 6-9Gi memory for 2 datasets
- [ ] **Action Required**: Verify Cloud SQL connection pooling can handle multiple jobs

### 3. Monitoring Setup
- [ ] **Action Required**: Create Kubernetes labels for dataset filtering
- [ ] **Action Required**: Set up logging queries for per-dataset monitoring
- [ ] **Action Required**: Configure alerts for job failures
- [ ] **Action Required**: Establish baseline metrics (current extraction rates)

---

## Phase 1: Safe Deployment (Week 1, Days 1-2)

**Goal**: Deploy feature-flagged processor with external steps disabled. No breaking changes.

### Timeline
- **Duration**: 2 days
- **Risk**: Very Low
- **Rollback**: Simple deployment revert

### Steps

#### Day 1: Merge and Build

1. **Review and merge PR #78**:
   ```bash
   # Review final changes
   git checkout copilot/refactor-pipeline-orchestration
   git pull origin copilot/refactor-pipeline-orchestration
   
   # Merge to feature branch
   git checkout feature/gcp-kubernetes-deployment
   git merge copilot/refactor-pipeline-orchestration
   git push origin feature/gcp-kubernetes-deployment
   ```

2. **Trigger processor build**:
   ```bash
   # Trigger Cloud Build (manual or automatic)
   gcloud builds triggers run build-processor-manual \
     --branch=feature/gcp-kubernetes-deployment
   
   # Monitor build progress
   gcloud builds list --filter="trigger_id=build-processor-manual" --limit=1
   ```

3. **Verify new image**:
   ```bash
   # List recent processor images
   gcloud artifacts docker images list \
     us-central1-docker.pkg.dev/mizzou-news-impact/mizzou-crawler/processor \
     --limit=5 --sort-by=~CREATE_TIME
   ```

#### Day 2: Deploy and Validate

4. **Update processor deployment**:
   ```bash
   # Apply updated deployment (with feature flags disabled)
   kubectl apply -f k8s/processor-deployment.yaml
   
   # Watch rollout
   kubectl rollout status deployment/mizzou-processor -n production
   ```

5. **Verify processor behavior**:
   ```bash
   # Check logs for feature flag status
   kubectl logs -n production -l app=mizzou-processor --tail=100 | grep "Enabled pipeline steps"
   ```
   
   **Expected output**:
   ```
   Enabled pipeline steps:
     - Discovery: ❌
     - Verification: ❌
     - Extraction: ❌
     - Cleaning: ✅
     - ML Analysis: ✅
     - Entity Extraction: ✅
   ```

6. **Monitor work queue**:
   ```bash
   kubectl logs -n production -l app=mizzou-processor --follow
   ```
   
   **Expected behavior**:
   - Processor continues cleaning/ML/entity extraction
   - No new extractions (`extraction_pending` stays at 0)
   - Existing cleaned articles continue through pipeline

### Success Criteria

- ✅ Processor deployment successful
- ✅ Logs show external steps disabled
- ✅ Cleaning, ML, and entity extraction continue normally
- ✅ No errors in processor logs
- ✅ Database queries show continued progress on existing articles

### Rollback Procedure

If issues occur:

```bash
# Revert to previous deployment
kubectl rollout undo deployment/mizzou-processor -n production

# Verify rollback
kubectl rollout status deployment/mizzou-processor -n production
kubectl logs -n production -l app=mizzou-processor --tail=50
```

---

## Phase 2: Mizzou Extraction Testing (Week 1, Days 3-7)

**Goal**: Run Mizzou extraction as standalone job while monitoring for issues.

### Timeline
- **Duration**: 5 days (includes 48-hour monitoring)
- **Risk**: Low
- **Rollback**: Delete job, re-enable extraction in processor

### Steps

#### Day 3: Deploy Mizzou Extraction Job

1. **Review and customize job manifest**:
   ```bash
   # Verify k8s/mizzou-extraction-job.yaml exists from PR #78
   cat k8s/mizzou-extraction-job.yaml
   ```

2. **Deploy extraction job**:
   ```bash
   # Apply job manifest
   kubectl apply -f k8s/mizzou-extraction-job.yaml
   
   # Verify job created
   kubectl get jobs -n production -l dataset=Mizzou
   ```

3. **Monitor job execution**:
   ```bash
   # Watch pod creation
   kubectl get pods -n production -l dataset=Mizzou -w
   
   # Follow job logs
   kubectl logs -n production -l dataset=Mizzou --follow
   ```

4. **Verify database updates**:
   ```sql
   -- Connect to Cloud SQL
   -- Check for new Mizzou extractions (last hour)
   SELECT COUNT(*) 
   FROM articles 
   WHERE status = 'extracted' 
   AND created_at > NOW() - INTERVAL '1 hour';
   
   -- Verify Mizzou-specific articles
   SELECT COUNT(a.id)
   FROM articles a
   JOIN candidate_links cl ON a.candidate_link_id = cl.id
   JOIN dataset_sources ds ON cl.source = (
     SELECT host FROM sources WHERE id = ds.source_id
   )
   JOIN datasets d ON ds.dataset_id = d.id
   WHERE d.slug = 'Mizzou'
   AND a.created_at > NOW() - INTERVAL '1 hour';
   ```

#### Days 4-5: Continuous Monitoring

5. **Monitor continuous processor integration**:
   ```bash
   # Watch processor logs
   kubectl logs -n production -l app=mizzou-processor --follow
   ```
   
   **Expected behavior**:
   - Processor picks up newly extracted Mizzou articles
   - Cleaning step processes articles (`status='extracted' → 'cleaned'`)
   - ML analysis step labels articles
   - Entity extraction step identifies locations

6. **Verify no conflicts**:
   - No duplicate processing
   - No rate limiting conflicts
   - No CAPTCHA blocks affecting processor
   - Job completes successfully

#### Days 6-7: Extended Monitoring

7. **Run multiple extraction jobs**:
   ```bash
   # Delete completed job
   kubectl delete job mizzou-extraction -n production
   
   # Rerun extraction
   kubectl apply -f k8s/mizzou-extraction-job.yaml
   
   # Monitor for consistency
   kubectl logs -n production -l dataset=Mizzou --follow
   ```

8. **Collect performance metrics**:
   ```sql
   -- Extraction rate analysis
   SELECT 
     DATE_TRUNC('hour', created_at) as hour,
     COUNT(*) as articles_extracted
   FROM articles
   WHERE created_at > NOW() - INTERVAL '3 days'
   GROUP BY hour
   ORDER BY hour DESC;
   
   -- Average extraction time (if tracked in telemetry)
   SELECT 
     operation_type,
     AVG(duration_seconds) as avg_duration,
     COUNT(*) as operation_count
   FROM operations
   WHERE operation_type = 'extraction'
   AND created_at > NOW() - INTERVAL '3 days'
   GROUP BY operation_type;
   ```

### Success Criteria

- ✅ Mizzou extraction job completes successfully (multiple runs)
- ✅ New articles appear in database with `status='extracted'`
- ✅ Continuous processor picks up articles for cleaning
- ✅ No duplicate processing detected
- ✅ No rate limiting conflicts
- ✅ No CAPTCHA blocks
- ✅ Performance metrics comparable to baseline

### Rollback Procedure

If issues occur:

```bash
# Delete extraction job
kubectl delete job mizzou-extraction -n production

# Re-enable extraction in processor
kubectl set env deployment/mizzou-processor -n production \
  ENABLE_EXTRACTION=true

# Verify processor resumes extraction
kubectl logs -n production -l app=mizzou-processor --tail=100 | grep "extraction"
```

---

## Phase 3: Mizzou Discovery Testing (Week 2, Days 8-10)

**Goal**: Verify discovery runs independently and finds new URLs.

### Timeline
- **Duration**: 3 days
- **Risk**: Low
- **Rollback**: Delete job, re-enable discovery in processor

### Steps

#### Day 8: Deploy Mizzou Discovery Job

1. **Deploy discovery job**:
   ```bash
   kubectl apply -f k8s/mizzou-discovery-job.yaml
   
   # Verify job created
   kubectl get jobs -n production -l dataset=Mizzou,type=discovery
   ```

2. **Monitor discovery execution**:
   ```bash
   kubectl logs -n production -l dataset=Mizzou,type=discovery --follow
   ```

3. **Verify candidate links created**:
   ```sql
   -- Check for new discovered URLs (last hour)
   SELECT COUNT(*) 
   FROM candidate_links 
   WHERE status = 'discovered'
   AND created_at > NOW() - INTERVAL '1 hour';
   
   -- Verify Mizzou-specific URLs
   SELECT cl.url, cl.status, cl.created_at
   FROM candidate_links cl
   JOIN dataset_sources ds ON cl.source = (
     SELECT host FROM sources WHERE id = ds.source_id
   )
   JOIN datasets d ON ds.dataset_id = d.id
   WHERE d.slug = 'Mizzou'
   AND cl.created_at > NOW() - INTERVAL '1 hour'
   ORDER BY cl.created_at DESC
   LIMIT 20;
   ```

#### Days 9-10: End-to-End Testing

4. **Run full pipeline: Discovery → Extraction → Processing**:
   ```bash
   # Run discovery
   kubectl delete job mizzou-discovery -n production
   kubectl apply -f k8s/mizzou-discovery-job.yaml
   
   # Wait for completion (check logs)
   kubectl logs -n production -l dataset=Mizzou,type=discovery --follow
   
   # Run extraction on newly discovered URLs
   kubectl delete job mizzou-extraction -n production
   kubectl apply -f k8s/mizzou-extraction-job.yaml
   
   # Monitor extraction
   kubectl logs -n production -l dataset=Mizzou,type=extraction --follow
   
   # Watch processor handle new articles
   kubectl logs -n production -l app=mizzou-processor --follow
   ```

5. **Verify no duplicate URLs**:
   ```sql
   -- Check for duplicate URLs
   SELECT url, COUNT(*) as count
   FROM candidate_links
   GROUP BY url
   HAVING COUNT(*) > 1;
   
   -- If duplicates exist, investigate source
   SELECT url, status, created_at, source
   FROM candidate_links
   WHERE url IN (
     SELECT url FROM candidate_links GROUP BY url HAVING COUNT(*) > 1
   )
   ORDER BY url, created_at;
   ```

### Success Criteria

- ✅ Discovery job finds new URLs successfully
- ✅ URLs marked as `status='discovered'`
- ✅ No duplicate URL issues
- ✅ Extraction job processes newly discovered URLs
- ✅ End-to-end pipeline works (discovery → extraction → cleaning → ML → entities)

### Rollback Procedure

```bash
# Delete discovery job
kubectl delete job mizzou-discovery -n production

# Re-enable discovery in processor (if needed)
kubectl set env deployment/mizzou-processor -n production \
  ENABLE_DISCOVERY=true
```

---

## Phase 4: Lehigh Migration (Week 2-3, Days 11-17)

**Goal**: Migrate Lehigh dataset to job-based extraction with aggressive rate limiting.

### Timeline
- **Duration**: 7 days
- **Risk**: Medium (Lehigh has aggressive bot protection)
- **Rollback**: Delete jobs, adjust rate limits

### Steps

#### Days 11-12: Lehigh Extraction Job

1. **Review Lehigh extraction manifest**:
   ```bash
   # Verify aggressive rate limiting configured
   cat k8s/lehigh-extraction-job.yaml | grep -A 10 "env:"
   ```
   
   **Expected rate limits**:
   ```yaml
   - name: INTER_REQUEST_MIN
     value: "90.0"   # 90 seconds
   - name: INTER_REQUEST_MAX
     value: "180.0"  # 3 minutes
   - name: BATCH_SLEEP_SECONDS
     value: "420.0"  # 7 minutes between batches
   ```

2. **Deploy Lehigh extraction job**:
   ```bash
   # NOTE: This may already exist from previous work (Issue #44)
   kubectl apply -f k8s/lehigh-extraction-job.yaml
   
   # Monitor carefully due to CAPTCHA risk
   kubectl logs -n production -l dataset=Penn-State-Lehigh --follow
   ```

3. **Watch for CAPTCHA blocks**:
   ```bash
   # Monitor logs for bot detection
   kubectl logs -n production -l dataset=Penn-State-Lehigh | grep -i "captcha\|blocked\|403\|bot"
   ```

#### Days 13-14: Lehigh Discovery Job

4. **Deploy Lehigh discovery job**:
   ```bash
   kubectl apply -f k8s/lehigh-discovery-job.yaml
   
   kubectl logs -n production -l dataset=Penn-State-Lehigh,type=discovery --follow
   ```

#### Days 15-17: Parallel Monitoring

5. **Monitor both datasets in parallel**:
   ```bash
   # Compare extraction logs
   kubectl logs -n production -l dataset=Mizzou,type=extraction --tail=50
   kubectl logs -n production -l dataset=Penn-State-Lehigh,type=extraction --tail=50
   
   # List all active jobs
   kubectl get jobs -n production -l type=extraction
   ```

6. **Verify isolation**:
   - Trigger CAPTCHA on Lehigh (if safe to test)
   - Verify Mizzou continues processing unaffected
   - Check processor logs show no impact

7. **Compare extraction rates**:
   ```sql
   -- Extraction counts by dataset (last 24 hours)
   SELECT 
     d.slug,
     COUNT(a.id) as articles_extracted,
     MIN(a.created_at) as first_extraction,
     MAX(a.created_at) as last_extraction
   FROM articles a
   JOIN candidate_links cl ON a.candidate_link_id = cl.id
   JOIN dataset_sources ds ON cl.source = (
     SELECT host FROM sources WHERE id = ds.source_id
   )
   JOIN datasets d ON ds.dataset_id = d.id
   WHERE a.created_at > NOW() - INTERVAL '24 hours'
   GROUP BY d.slug;
   ```

### Success Criteria

- ✅ Both datasets process independently
- ✅ Different rate limiting works correctly (Mizzou 5-15s, Lehigh 90-180s)
- ✅ CAPTCHA on Lehigh doesn't affect Mizzou
- ✅ Continuous processor handles articles from both datasets
- ✅ No cross-dataset interference
- ✅ Lehigh extraction completes without excessive CAPTCHA blocks

### Rollback Procedure

```bash
# Delete Lehigh jobs
kubectl delete job lehigh-extraction -n production
kubectl delete job lehigh-discovery -n production

# If needed, adjust rate limiting and redeploy
# Edit k8s/lehigh-extraction-job.yaml (increase delays)
kubectl apply -f k8s/lehigh-extraction-job.yaml
```

---

## Phase 5: Scheduled Discovery (Week 3, Days 18-21)

**Goal**: Automate daily discovery runs using Kubernetes CronJobs.

### Timeline
- **Duration**: 4 days
- **Risk**: Low
- **Rollback**: Delete CronJobs, run manual jobs

### Steps

#### Day 18: Create CronJob Manifests

1. **Create Mizzou discovery CronJob**:
   ```bash
   # Create from job template
   cat > k8s/mizzou-discovery-cronjob.yaml << 'EOF'
   apiVersion: batch/v1
   kind: CronJob
   metadata:
     name: mizzou-discovery-daily
     namespace: production
     labels:
       app: mizzou-crawler
       dataset: Mizzou
       type: discovery
   spec:
     schedule: "0 6 * * *"  # Daily at 6 AM UTC (1 AM CST)
     successfulJobsHistoryLimit: 3
     failedJobsHistoryLimit: 3
     jobTemplate:
       # Copy spec from k8s/mizzou-discovery-job.yaml
       spec:
         # ... (same as Job)
   EOF
   ```

2. **Create Lehigh discovery CronJob**:
   ```bash
   cat > k8s/lehigh-discovery-cronjob.yaml << 'EOF'
   apiVersion: batch/v1
   kind: CronJob
   metadata:
     name: lehigh-discovery-daily
     namespace: production
     labels:
       app: mizzou-crawler
       dataset: Penn-State-Lehigh
       type: discovery
   spec:
     schedule: "0 7 * * *"  # Daily at 7 AM UTC (avoid overlap with Mizzou)
     successfulJobsHistoryLimit: 3
     failedJobsHistoryLimit: 3
     jobTemplate:
       # Copy spec from k8s/lehigh-discovery-job.yaml
       spec:
         # ... (same as Job)
   EOF
   ```

#### Days 19-20: Deploy and Test

3. **Deploy CronJobs**:
   ```bash
   kubectl apply -f k8s/mizzou-discovery-cronjob.yaml
   kubectl apply -f k8s/lehigh-discovery-cronjob.yaml
   
   # Verify CronJobs created
   kubectl get cronjobs -n production
   ```

4. **Trigger manual test runs**:
   ```bash
   # Manually trigger Mizzou discovery
   kubectl create job mizzou-discovery-test-1 \
     --from=cronjob/mizzou-discovery-daily -n production
   
   # Watch execution
   kubectl logs -n production -l job-name=mizzou-discovery-test-1 --follow
   
   # Manually trigger Lehigh discovery
   kubectl create job lehigh-discovery-test-1 \
     --from=cronjob/lehigh-discovery-daily -n production
   
   # Watch execution
   kubectl logs -n production -l job-name=lehigh-discovery-test-1 --follow
   ```

#### Day 21: Wait for Scheduled Runs

5. **Monitor first scheduled runs**:
   ```bash
   # Check CronJob status before scheduled time
   kubectl get cronjobs -n production -o wide
   
   # Watch for job creation at 6 AM UTC (Mizzou)
   watch kubectl get jobs -n production -l type=discovery
   
   # Check logs of scheduled job
   kubectl logs -n production -l job-name=<auto-generated-name> --follow
   ```

6. **Verify job history**:
   ```bash
   # List recent discovery jobs
   kubectl get jobs -n production -l type=discovery --sort-by=.metadata.creationTimestamp
   
   # Check CronJob status
   kubectl describe cronjob mizzou-discovery-daily -n production
   ```

### Success Criteria

- ✅ CronJobs appear in Kubernetes with correct schedule
- ✅ Manual test runs execute successfully
- ✅ First scheduled runs execute at correct time (6 AM UTC, 7 AM UTC)
- ✅ Discovery finds new URLs daily
- ✅ Job history maintained (3 successful, 3 failed)

### Rollback Procedure

```bash
# Delete CronJobs
kubectl delete cronjob mizzou-discovery-daily -n production
kubectl delete cronjob lehigh-discovery-daily -n production

# Clean up test jobs
kubectl delete job -n production -l type=discovery

# Resume manual job execution
kubectl apply -f k8s/mizzou-discovery-job.yaml
kubectl apply -f k8s/lehigh-discovery-job.yaml
```

---

## Phase 6: Production Stabilization (Week 4, Days 22-28)

**Goal**: Monitor production operation and optimize configurations.

### Timeline
- **Duration**: 7 days
- **Risk**: Very Low (stabilization phase)

### Steps

#### Days 22-24: Monitoring and Optimization

1. **Collect performance data**:
   ```sql
   -- Pipeline throughput by dataset (last 7 days)
   SELECT 
     d.slug,
     COUNT(CASE WHEN cl.status = 'discovered' THEN 1 END) as discovered,
     COUNT(CASE WHEN cl.status = 'article' THEN 1 END) as verified,
     COUNT(CASE WHEN a.status = 'extracted' THEN 1 END) as extracted,
     COUNT(CASE WHEN a.status = 'cleaned' THEN 1 END) as cleaned,
     COUNT(CASE WHEN a.primary_label IS NOT NULL THEN 1 END) as analyzed
   FROM datasets d
   JOIN dataset_sources ds ON d.id = ds.dataset_id
   JOIN sources s ON ds.source_id = s.id
   LEFT JOIN candidate_links cl ON s.host = cl.source
   LEFT JOIN articles a ON cl.id = a.candidate_link_id
   WHERE a.created_at > NOW() - INTERVAL '7 days'
   GROUP BY d.slug;
   
   -- Average extraction rate (articles per hour)
   SELECT 
     d.slug,
     DATE_TRUNC('hour', a.created_at) as hour,
     COUNT(*) as articles_per_hour
   FROM articles a
   JOIN candidate_links cl ON a.candidate_link_id = cl.id
   JOIN dataset_sources ds ON cl.source = (
     SELECT host FROM sources WHERE id = ds.source_id
   )
   JOIN datasets d ON ds.dataset_id = d.id
   WHERE a.created_at > NOW() - INTERVAL '7 days'
   GROUP BY d.slug, hour
   ORDER BY d.slug, hour DESC;
   ```

2. **Review error rates**:
   ```bash
   # Check for extraction failures
   kubectl logs -n production -l type=extraction | grep -i "error\|failed\|exception"
   
   # Check processor errors
   kubectl logs -n production -l app=mizzou-processor | grep -i "error\|failed\|exception"
   ```

3. **Optimize rate limiting** (if needed):
   - Review CAPTCHA occurrence frequency
   - Adjust `INTER_REQUEST_MIN/MAX` based on block patterns
   - Update job manifests and redeploy

#### Days 25-26: Resource Optimization

4. **Review resource usage**:
   ```bash
   # Check pod resource consumption
   kubectl top pods -n production -l app=mizzou-crawler
   
   # Review job completion times
   kubectl get jobs -n production -l type=extraction -o json | \
     jq '.items[] | {name: .metadata.name, duration: (.status.completionTime - .status.startTime)}'
   ```

5. **Adjust resource limits** (if needed):
   ```yaml
   # Edit job manifests
   resources:
     requests:
       cpu: "500m"      # Adjust based on usage
       memory: "1Gi"
     limits:
       cpu: "1000m"
       memory: "2Gi"
   ```

#### Days 27-28: Documentation and Knowledge Transfer

6. **Update documentation**:
   - Document observed rate limiting sweet spots
   - Add troubleshooting procedures based on issues encountered
   - Update runbooks with new monitoring queries

7. **Create operational dashboards** (optional):
   - GCP Cloud Monitoring dashboard for job metrics
   - Kubernetes dashboard for pod health
   - Database queries for pipeline status

### Success Criteria

- ✅ All datasets processing smoothly for 7+ days
- ✅ Error rates within acceptable range (<5%)
- ✅ Resource usage optimized (no over/under provisioning)
- ✅ Documentation updated with production insights
- ✅ Team comfortable with new architecture

---

## Post-Rollout: Maintenance and Scaling

### Adding New Datasets

1. **Use templates** from PR #78:
   ```bash
   cp k8s/templates/dataset-discovery-job.yaml k8s/newdataset-discovery-job.yaml
   cp k8s/templates/dataset-extraction-job.yaml k8s/newdataset-extraction-job.yaml
   ```

2. **Customize for new dataset**:
   - Replace `DATASET_SLUG` with actual identifier
   - Adjust `--max-articles`, `--days-back`, `--limit`, `--batches`
   - Configure rate limiting based on site behavior
   - Set appropriate resource limits

3. **Deploy and test**:
   ```bash
   kubectl apply -f k8s/newdataset-discovery-job.yaml
   kubectl apply -f k8s/newdataset-extraction-job.yaml
   
   kubectl logs -n production -l dataset=NEWDATASET --follow
   ```

4. **Convert to CronJob** (once stable):
   ```bash
   # Create CronJob manifest from job template
   kubectl apply -f k8s/newdataset-discovery-cronjob.yaml
   ```

### Monitoring Procedures

**Daily**:
- Check CronJob execution status: `kubectl get cronjobs -n production`
- Review error logs: `kubectl logs -n production -l app=mizzou-crawler | grep -i error`
- Monitor database queue depths (discovered, extracted, cleaned, analyzed)

**Weekly**:
- Review extraction rates by dataset
- Analyze CAPTCHA occurrence patterns
- Optimize rate limiting configurations
- Check resource usage trends

**Monthly**:
- Review overall pipeline throughput
- Assess need for new datasets
- Plan infrastructure scaling
- Update documentation

---

## Risk Management

### Identified Risks

1. **CAPTCHA Escalation on Lehigh**
   - **Mitigation**: Aggressive rate limiting (90-180s), exponential backoff
   - **Detection**: Monitor logs for "CAPTCHA" or "403" errors
   - **Response**: Increase delays, pause extraction temporarily

2. **Resource Exhaustion**
   - **Mitigation**: Resource limits on all pods, monitoring alerts
   - **Detection**: `kubectl top pods` shows high usage
   - **Response**: Scale up cluster, optimize batch sizes

3. **Database Connection Limits**
   - **Mitigation**: Connection pooling, stagger job execution
   - **Detection**: Connection errors in logs
   - **Response**: Adjust pool size, increase Cloud SQL capacity

4. **Duplicate Processing**
   - **Mitigation**: Database constraints, careful scheduling
   - **Detection**: Query for duplicate URLs or articles
   - **Response**: Review job scheduling, check for race conditions

### Rollback Triggers

Initiate immediate rollback if:
- Processor crashes or enters crash loop (>3 restarts in 10 minutes)
- Data corruption detected (duplicate articles, missing fields)
- Cloud SQL connection saturation (>80% connections used)
- Excessive CAPTCHA blocks on multiple datasets (>10 per hour)
- Critical business metrics drop (>50% reduction in throughput)

### Emergency Contacts

- **Platform Owner**: dkiesow
- **GCP Project**: mizzou-news-impact
- **Kubernetes Cluster**: production (us-central1)
- **Cloud SQL Instance**: mizzou-news-production

---

## Success Metrics

### Phase Completion Criteria

| Phase | Metric | Target |
|-------|--------|--------|
| Phase 1 | Processor deployment success | ✅ 100% |
| Phase 1 | Logs show feature flags disabled | ✅ Yes |
| Phase 2 | Mizzou extraction success rate | ✅ >95% |
| Phase 2 | Processor picks up new articles | ✅ Yes |
| Phase 3 | Discovery finds new URLs | ✅ >20 per run |
| Phase 3 | No duplicate URLs | ✅ <1% |
| Phase 4 | Lehigh extraction success rate | ✅ >90% |
| Phase 4 | No cross-dataset interference | ✅ Yes |
| Phase 5 | CronJob execution | ✅ 100% |
| Phase 6 | 7-day stability | ✅ <5% error rate |

### Long-Term KPIs

- **Throughput**: Articles processed per hour (baseline + 10%)
- **Reliability**: Job success rate >95%
- **Isolation**: CAPTCHA blocks don't affect other datasets
- **Scalability**: Add new dataset in <2 hours
- **Maintainability**: Clear per-dataset monitoring

---

## Conclusion

This phased rollout plan ensures a safe, gradual migration to the refactored orchestration architecture. Each phase has clear success criteria, monitoring procedures, and rollback plans.

**Key Milestones**:
- Week 1: Feature-flagged deployment + Mizzou extraction
- Week 2: Mizzou discovery + Lehigh migration
- Week 3: Scheduled discovery via CronJobs
- Week 4: Production stabilization

**Expected Outcomes**:
- Independent dataset processing with custom rate limiting
- Isolated CAPTCHA backoff preventing cross-dataset impact
- Clear monitoring and troubleshooting per dataset
- Easy scaling via job templates

**Next Steps**:
1. Review this plan with team
2. Complete pre-deployment checklist
3. Begin Phase 1 (Week 1, Days 1-2)

---

**Document Version**: 1.0  
**Last Updated**: October 15, 2025  
**Status**: Ready for Team Review
