# Orchestration Migration Guide

This guide walks through the migration from the monolithic continuous processor to the refactored dataset-specific job architecture.

## Overview

The refactoring (Issue #77) separates external site interaction from internal processing for better scalability and monitoring.

## Migration Phases

### Phase 1: Deploy Feature-Flagged Processor (Safe, No Breaking Changes)

**Goal**: Deploy the refactored processor with all external steps disabled, continue using existing processor for extraction.

**Steps**:

1. **Update processor deployment**:
   ```bash
   kubectl apply -f k8s/processor-deployment.yaml
   ```

2. **Verify processor logs**:
   ```bash
   kubectl logs -n production -l app=mizzou-processor --follow
   ```
   
   You should see:
   ```
   🚀 Starting continuous processor
   Configuration:
     - Poll interval: 60 seconds
     ...
   
   Enabled pipeline steps:
     - Discovery: ❌
     - Verification: ❌
     - Extraction: ❌
     - Cleaning: ✅
     - ML Analysis: ✅
     - Entity Extraction: ✅
   ```

3. **Monitor work queue**:
   The processor will now only check for cleaning, ML, and entity extraction work:
   ```
   Work queue status: {
     'verification_pending': 0,
     'extraction_pending': 0,
     'cleaning_pending': 25,
     'analysis_pending': 30,
     'entity_extraction_pending': 40
   }
   ```

**Validation**:
- Processor continues to process cleaned articles
- No new extractions happen (extraction_pending stays at 0)
- Cleaning, ML, and entity extraction continue normally

**Rollback**:
If issues occur, revert to previous deployment:
```bash
kubectl rollout undo deployment/mizzou-processor -n production
```

### Phase 2: Test Mizzou Extraction Job (Parallel Operation)

**Goal**: Run Mizzou extraction as a standalone job while monitoring for issues.

**Steps**:

1. **Create Mizzou extraction job**:
   ```bash
   kubectl apply -f k8s/mizzou-extraction-job.yaml
   ```

2. **Monitor job progress**:
   ```bash
   # Watch job logs
   kubectl logs -n production -l dataset=Mizzou --follow
   
   # Check job status
   kubectl get jobs -n production -l dataset=Mizzou
   
   # Check pod status
   kubectl get pods -n production -l dataset=Mizzou
   ```

3. **Verify database updates**:
   ```sql
   -- Check for new articles extracted
   SELECT COUNT(*) 
   FROM articles 
   WHERE status = 'extracted' 
   AND created_at > NOW() - INTERVAL '1 hour';
   
   -- Check for Mizzou-specific extractions
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

4. **Monitor continuous processor**:
   ```bash
   kubectl logs -n production -l app=mizzou-processor --follow
   ```
   
   Verify it picks up newly extracted articles for cleaning:
   ```
   ✅ Content cleaning (25 pending, limit 25) completed successfully
   ```

**Validation**:
- Mizzou extraction job completes successfully
- New articles appear in database with status='extracted'
- Continuous processor picks up articles for cleaning
- No rate limiting conflicts or CAPTCHA blocks

**Rollback**:
If issues occur:
```bash
# Delete the extraction job
kubectl delete job mizzou-extraction -n production

# Re-enable extraction in processor
kubectl set env deployment/mizzou-processor -n production ENABLE_EXTRACTION=true
```

### Phase 3: Test Mizzou Discovery Job

**Goal**: Verify discovery runs independently.

**Steps**:

1. **Create Mizzou discovery job**:
   ```bash
   kubectl apply -f k8s/mizzou-discovery-job.yaml
   ```

2. **Monitor job progress**:
   ```bash
   kubectl logs -n production -l dataset=Mizzou,type=discovery --follow
   ```

3. **Verify candidate links**:
   ```sql
   -- Check for new discovered URLs
   SELECT COUNT(*) 
   FROM candidate_links 
   WHERE status = 'discovered'
   AND created_at > NOW() - INTERVAL '1 hour';
   ```

**Validation**:
- Discovery job finds new URLs
- URLs are marked as status='discovered'
- No duplicate URL issues

### Phase 4: Deploy Lehigh Jobs (Repeat Pattern)

**Goal**: Migrate Lehigh dataset to job-based extraction.

**Steps**:

1. **Update Lehigh extraction job** (if needed):
   ```bash
   kubectl apply -f k8s/lehigh-extraction-job.yaml
   ```

2. **Create Lehigh discovery job**:
   ```bash
   kubectl apply -f k8s/lehigh-discovery-job.yaml
   ```

3. **Monitor both datasets**:
   ```bash
   # Watch all extraction jobs
   kubectl get jobs -n production -l type=extraction
   
   # Compare extraction rates
   kubectl logs -n production -l dataset=Mizzou,type=extraction --tail=100
   kubectl logs -n production -l dataset=Penn-State-Lehigh,type=extraction --tail=100
   ```

**Validation**:
- Both datasets process independently
- Different rate limiting configurations work correctly
- CAPTCHA on Lehigh doesn't affect Mizzou
- Continuous processor handles both datasets' articles

### Phase 5: Schedule Discovery Jobs (CronJobs)

**Goal**: Automate daily discovery runs.

**Steps**:

1. **Create CronJob manifests**:
   
   `k8s/mizzou-discovery-cronjob.yaml`:
   ```yaml
   apiVersion: batch/v1
   kind: CronJob
   metadata:
     name: mizzou-discovery-daily
     namespace: production
   spec:
     schedule: "0 6 * * *"  # Daily at 6 AM UTC
     jobTemplate:
       spec:
         # Copy from mizzou-discovery-job.yaml
         template:
           # ...
   ```

2. **Deploy CronJobs**:
   ```bash
   kubectl apply -f k8s/mizzou-discovery-cronjob.yaml
   kubectl apply -f k8s/lehigh-discovery-cronjob.yaml
   ```

3. **Verify schedule**:
   ```bash
   kubectl get cronjobs -n production
   ```

**Validation**:
- CronJobs appear in list with correct schedule
- Test runs execute at scheduled time
- Discovery finds new URLs daily

### Phase 6: Scale to Additional Datasets

**Goal**: Add new datasets using the template pattern.

**For each new dataset**:

1. Copy templates:
   ```bash
   cp k8s/templates/dataset-discovery-job.yaml k8s/newdataset-discovery-job.yaml
   cp k8s/templates/dataset-extraction-job.yaml k8s/newdataset-extraction-job.yaml
   ```

2. Customize placeholders:
   - Replace `DATASET_SLUG` with actual dataset identifier
   - Update `PROCESSOR_IMAGE` to latest image
   - Adjust rate limiting based on site behavior
   - Configure resource limits

3. Deploy:
   ```bash
   kubectl apply -f k8s/newdataset-discovery-job.yaml
   kubectl apply -f k8s/newdataset-extraction-job.yaml
   ```

4. Monitor initial run:
   ```bash
   kubectl logs -n production -l dataset=NEWDATASET --follow
   ```

## Monitoring After Migration

### Database Queries

**Pipeline Status by Dataset**:
```sql
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
GROUP BY d.slug;
```

**Extraction Rate (Last Hour)**:
```sql
SELECT 
  d.slug,
  COUNT(*) as articles_extracted,
  MIN(a.created_at) as first_extraction,
  MAX(a.created_at) as last_extraction
FROM articles a
JOIN candidate_links cl ON a.candidate_link_id = cl.id
JOIN dataset_sources ds ON cl.source = (
  SELECT host FROM sources WHERE id = ds.source_id
)
JOIN datasets d ON ds.dataset_id = d.id
WHERE a.created_at > NOW() - INTERVAL '1 hour'
GROUP BY d.slug;
```

### Kubernetes Commands

**List All Jobs by Type**:
```bash
kubectl get jobs -n production -l type=extraction
kubectl get jobs -n production -l type=discovery
```

**Check Job Status**:
```bash
kubectl describe job mizzou-extraction -n production
```

**View Recent Logs**:
```bash
kubectl logs -n production -l dataset=Mizzou --tail=500
```

**Delete Completed Jobs**:
```bash
kubectl delete job -n production -l type=extraction,status=Complete
```

## Troubleshooting

### Issue: Extraction Job Stuck

**Symptoms**: Job shows as running but no progress in logs.

**Diagnosis**:
```bash
kubectl get pods -n production -l dataset=DATASET
kubectl logs -n production -l dataset=DATASET --tail=100
```

**Solutions**:
- Check for CAPTCHA blocks in logs
- Increase rate limiting delays
- Verify database connectivity
- Check resource limits (CPU/memory)

### Issue: Continuous Processor Not Picking Up Articles

**Symptoms**: Articles stuck in 'extracted' status.

**Diagnosis**:
```bash
kubectl logs -n production -l app=mizzou-processor --tail=100
```

**Solutions**:
- Verify `ENABLE_CLEANING=true` in deployment
- Check database connection
- Restart processor pod if stuck

### Issue: Duplicate URL Discovery

**Symptoms**: Same URLs discovered multiple times.

**Diagnosis**:
```sql
SELECT url, COUNT(*) 
FROM candidate_links 
GROUP BY url 
HAVING COUNT(*) > 1;
```

**Solutions**:
- Check discovery job scheduling (avoid overlaps)
- Verify dataset filtering in discover-urls command
- Review source deduplication logic

## Rollback Procedures

### Complete Rollback to Monolithic Processor

If major issues occur:

1. **Re-enable all steps in processor**:
   ```bash
   kubectl set env deployment/mizzou-processor -n production \
     ENABLE_DISCOVERY=true \
     ENABLE_VERIFICATION=true \
     ENABLE_EXTRACTION=true
   ```

2. **Delete all dataset jobs**:
   ```bash
   kubectl delete jobs -n production -l type=extraction
   kubectl delete jobs -n production -l type=discovery
   ```

3. **Verify processor resumes**:
   ```bash
   kubectl logs -n production -l app=mizzou-processor --follow
   ```

### Partial Rollback (Single Dataset)

To rollback just one dataset:

1. **Delete dataset jobs**:
   ```bash
   kubectl delete job mizzou-extraction -n production
   kubectl delete job mizzou-discovery -n production
   ```

2. **Re-enable extraction for that dataset in processor** (requires code change):
   - Modify processor to enable extraction for specific datasets
   - Or temporarily enable extraction globally

## Success Criteria

After completing migration:

- ✅ All datasets process independently
- ✅ Different rate limiting per dataset works correctly
- ✅ CAPTCHA on one dataset doesn't affect others
- ✅ Continuous processor handles cleaning/ML/entities for all datasets
- ✅ ML models loaded once, shared across all processing
- ✅ Clear monitoring per dataset
- ✅ Easy to add new datasets

## Next Steps

After successful migration:

1. Schedule regular discovery runs via CronJobs
2. Set up monitoring dashboards per dataset
3. Document rate limiting best practices per site
4. Consider auto-scaling based on queue depth
5. Explore automatic job triggering when URLs are ready

## Related Documentation

- [docs/ORCHESTRATION_ARCHITECTURE.md](ORCHESTRATION_ARCHITECTURE.md) - Architecture details
- [k8s/templates/README.md](../k8s/templates/README.md) - Job templates
- [Issue #77](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/77) - Original issue
