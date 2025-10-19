# Deployment Guide: ML Model Loading Optimization

This guide covers deploying the ML model loading optimization changes to production.

## Overview

The optimization eliminates repeated spaCy model reloads by:
1. Increasing batch size from 50 to 500 articles (Phase 1)
2. Caching the model in memory and using direct function calls (Phase 2)

## Pre-Deployment Checklist

- [ ] Code review completed
- [ ] Tests passing
- [ ] Documentation reviewed
- [ ] Deployment plan approved
- [ ] Rollback plan ready

## Deployment Steps

### 1. Build New Processor Image

The changes are in the processor service, so we need to rebuild the processor image:

```bash
# Trigger processor image build
gcloud builds triggers run build-processor-manual \
  --branch=<your-branch-name>

# Wait for build to complete
gcloud builds list --limit=1 --filter="tags:processor"
```

### 2. Update Kubernetes Deployment

The new processor image will be automatically deployed if using continuous deployment. Otherwise:

```bash
# Get the new image tag
NEW_IMAGE=$(gcloud builds list --limit=1 --filter="tags:processor" --format="value(images[0])")

# Update the deployment
kubectl set image deployment/mizzou-processor \
  processor=${NEW_IMAGE} \
  -n production

# Monitor rollout
kubectl rollout status deployment/mizzou-processor -n production
```

### 3. Verify Deployment

#### Check Pod Logs

```bash
# Get processor pod name
POD=$(kubectl get pod -n production -l app=mizzou-processor -o name | head -1)

# Check logs for model loading
kubectl logs -f ${POD} -n production | grep -E "Loading spaCy|spaCy model loaded"
```

**Expected Output:**
```
[INFO] 🧠 Loading spaCy model (one-time initialization)...
[INFO] ✅ spaCy model loaded and cached in memory
```

This should appear **only once** at pod startup, not on every batch.

#### Monitor Memory Usage

```bash
# Watch memory usage (should be constant ~2.5GB)
watch kubectl top pod -n production -l app=mizzou-processor
```

**Expected:**
- Initial spike to ~2.5GB when model loads
- Memory stays constant (no spikes every 5 minutes)
- No gradual memory growth

#### Check Entity Extraction Batches

```bash
# Monitor entity extraction logs
kubectl logs -f ${POD} -n production | grep "Entity extraction"
```

**Expected Output:**
```
[INFO] ▶️  Entity extraction (1234 pending, limit 500)
[INFO] ✅ Entity extraction completed successfully (45.2s)
```

Notice:
- Batch limit is now 500 (was 50)
- No "Loading spaCy model" between batches
- Faster processing (no startup overhead)

### 4. Performance Validation

#### Check Processing Metrics

After 1 hour of operation:

```bash
# Count entity extraction runs in last hour
kubectl logs ${POD} -n production --since=1h | \
  grep -c "Entity extraction completed"

# Should be ~12 runs/hour (one every 5 minutes)
# Previously would have 288 model loads/day (12/hour)
# Now should have 1 model load total (at startup)
```

#### Verify No Model Reloads

```bash
# Count model load messages
kubectl logs ${POD} -n production --since=1h | \
  grep -c "Loading spaCy model"

# Should be 0 (model was loaded at startup, before the 1h window)
# If pod restarted during the hour, should be 1
```

#### Check Memory Stability

```bash
# Get memory metrics from Grafana/Cloud Monitoring
# Or use kubectl top over time
for i in {1..12}; do
  kubectl top pod -n production -l app=mizzou-processor
  sleep 300  # Wait 5 minutes between checks
done
```

**Expected:**
- Memory stays constant around 2.5GB ± 100MB
- No spikes to 4.5GB (2.5GB + 2GB spike)
- No OOM events

## Rollback Procedure

If issues are detected, rollback to the previous version:

```bash
# Rollback deployment
kubectl rollout undo deployment/mizzou-processor -n production

# Monitor rollback
kubectl rollout status deployment/mizzou-processor -n production

# Verify old behavior restored
kubectl logs -f deployment/mizzou-processor -n production
```

## Configuration Options

### Environment Variables

The batch size can be tuned via environment variable:

```yaml
# k8s/processor-deployment.yaml
env:
  - name: GAZETTEER_BATCH_SIZE
    value: "500"  # Default is 500, can be adjusted
```

**Tuning Guidelines:**
- **Smaller batches (100-300):** More frequent processing, lower memory usage
- **Larger batches (500-1000):** Less frequent processing, higher throughput
- **Very large batches (1000+):** Best throughput, but longer-running processes risk interruption

### Memory Limits

The processor may need memory limits adjusted:

```yaml
# k8s/processor-deployment.yaml
resources:
  requests:
    memory: 3Gi  # Increased from 2Gi to account for cached model
  limits:
    memory: 4Gi  # Safety margin for peak usage
```

## Monitoring

### Key Metrics to Watch

1. **Model Load Frequency:**
   - Should be 1/pod-lifetime (only at startup)
   - Alert if > 2/hour (indicates issue with caching)

2. **Memory Usage:**
   - Should be constant ~2.5GB
   - Alert if > 3.5GB sustained or trending up
   - Alert if frequent OOM kills

3. **Processing Throughput:**
   - Should increase (no startup overhead per batch)
   - Alert if throughput decreases

4. **Entity Extraction Latency:**
   - Should decrease (no model loading time)
   - Alert if latency increases

### Grafana Dashboards

Add these queries to your monitoring dashboard:

```promql
# Model load frequency (should be ~0 after startup)
rate(log_messages{message=~".*Loading spaCy model.*"}[1h])

# Memory usage (should be constant)
container_memory_usage_bytes{container="mizzou-processor"}

# Entity extraction batch size (should be 500)
histogram_quantile(0.95, 
  rate(entity_extraction_batch_size_bucket[5m])
)
```

## Success Criteria

After 24 hours of operation:

- ✅ Model loaded exactly once per pod (check logs)
- ✅ No memory spikes every 5 minutes (constant ~2.5GB)
- ✅ No OOM kills in processor pods
- ✅ Entity extraction throughput maintained or improved
- ✅ Batch size consistently 500 articles (check logs)
- ✅ Processing time reduced (no startup overhead)

## Troubleshooting

### Issue: Model Still Reloading

**Symptoms:** Log shows "Loading spaCy model" multiple times after startup

**Cause:** Cached extractor not being used

**Solution:**
1. Check that Phase 2 changes were deployed (verify image tag)
2. Verify no exceptions in `get_cached_entity_extractor()`
3. Check that `process_entity_extraction()` is calling the function directly

### Issue: Memory Usage Higher Than Expected

**Symptoms:** Memory > 4GB sustained

**Cause:** Possible memory leak or multiple models loaded

**Solution:**
1. Check for multiple entity extractor instances (should be 1)
2. Review logs for exceptions that might cause extractor recreation
3. Use memory profiler to identify leak source
4. Consider reducing batch size temporarily

### Issue: Entity Extraction Failing

**Symptoms:** Entity extraction returns error code 1

**Cause:** Exception in direct function call

**Solution:**
1. Check processor logs for exception details
2. Verify database connectivity
3. Check that extractor was properly initialized
4. Rollback if issue persists

## Contact

For issues or questions:
- GitHub Issues: https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues
- Development Team: @dkiesow

## References

- [ML_MODEL_OPTIMIZATION.md](./ML_MODEL_OPTIMIZATION.md) - Implementation details
- [ML_MODEL_RELOADING_ANALYSIS.md](../ML_MODEL_RELOADING_ANALYSIS.md) - Original analysis
- [GitHub Issue #90](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/90)
