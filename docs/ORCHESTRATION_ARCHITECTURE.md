# Orchestration Architecture

**Issue #77: Refactored Pipeline Orchestration**

This document describes the refactored orchestration architecture that separates external site interaction (dataset jobs) from internal processing (continuous processor).

## Overview

The orchestration refactoring separates the pipeline into two components:

1. **Dataset-Specific Jobs** - Handle external site interaction (discovery, verification, extraction)
2. **Continuous Processor** - Handle internal processing (cleaning, ML analysis, entity extraction)

## Benefits

- ✅ **Independent Rate Limiting**: Each dataset can have its own rate limiting configuration
- ✅ **Isolated CAPTCHA Backoff**: CAPTCHA blocks on one dataset don't affect others
- ✅ **Better Monitoring**: Clear separation of concerns with distinct pods per dataset
- ✅ **Scalability**: Easy to add new datasets by copying job templates
- ✅ **Resource Efficiency**: ML models loaded once, shared across all datasets
- ✅ **Fault Isolation**: Failures in one dataset don't impact others

## Architecture Diagram

### Before (Monolithic)

```
mizzou-processor (continuous):
  ├─ Discovery (all datasets)          ← mixing rate limits!
  ├─ Verification (all datasets)       ← mixing rate limits!
  ├─ Extraction (all datasets)         ← mixing rate limits!
  ├─ Cleaning (all datasets)
  ├─ ML Analysis (all datasets)
  └─ Entity Extraction (all datasets)
```

### After (Separated)

```
Dataset-Specific Jobs (per dataset):
  ├─ {dataset}-discovery-job (scheduled)
  │   └─ Discover URLs → status='discovered'
  └─ {dataset}-extraction-job (on-demand/scheduled)
      ├─ Verify URLs → status='article'
      └─ Extract content → status='extracted'

Continuous Processor (shared):
  ├─ Cleaning (status='extracted' → 'cleaned')
  ├─ ML Analysis (status='cleaned' → labeled)
  └─ Entity Extraction (labeled → entities)
```

## Components

### Dataset Jobs

#### Discovery Job

**Purpose**: Find new article URLs from RSS feeds, sitemaps, and homepages.

**Configuration**:
- Dataset-specific (filtered by `--dataset` flag)
- Scheduled (CronJob) or on-demand (Job)
- Lightweight resource requirements

**Example**: `k8s/mizzou-discovery-job.yaml`

```yaml
command:
  - discover-urls
  - --dataset
  - Mizzou
  - --max-articles
  - "50"
  - --days-back
  - "7"
```

#### Extraction Job

**Purpose**: Fetch and extract article content from verified URLs.

**Configuration**:
- Dataset-specific (filtered by `--dataset` flag)
- On-demand (Job) triggered when URLs are ready
- Includes verification step (status='discovered' → 'article')
- Heavy resource requirements (external HTTP requests)
- Custom rate limiting per dataset

**Example**: `k8s/mizzou-extraction-job.yaml`

```yaml
command:
  - extract
  - --dataset
  - Mizzou
  - --limit
  - "20"
  - --batches
  - "60"
env:
  - name: INTER_REQUEST_MIN
    value: "5.0"   # 5 seconds (faster than Lehigh)
  - name: INTER_REQUEST_MAX
    value: "15.0"  # 15 seconds
```

### Continuous Processor

**Purpose**: Shared internal processing for all datasets.

**Configuration**:
- Runs continuously (Deployment)
- Feature flags control which steps are enabled
- Focuses on CPU-intensive tasks (cleaning, ML, entities)
- No external HTTP requests (no rate limiting needed)

**Environment Variables**:

```yaml
# Pipeline step feature flags
- name: ENABLE_DISCOVERY
  value: "false"  # Moved to dataset jobs
- name: ENABLE_VERIFICATION
  value: "false"  # Moved to dataset jobs
- name: ENABLE_EXTRACTION
  value: "false"  # Moved to dataset jobs
- name: ENABLE_CLEANING
  value: "true"   # Keep in continuous processor
- name: ENABLE_ML_ANALYSIS
  value: "true"   # Keep in continuous processor
- name: ENABLE_ENTITY_EXTRACTION
  value: "true"   # Keep in continuous processor
```

## Data Flow

### Pipeline Stages

```
1. Discovery Job (per dataset)
   └─> candidate_links (status='discovered')

2. Extraction Job (per dataset)
   ├─> Verification: 'discovered' → 'article'
   └─> Extraction: 'article' → articles (status='extracted')

3. Continuous Processor (shared)
   ├─> Cleaning: 'extracted' → 'cleaned'
   ├─> ML Analysis: 'cleaned' → labeled (primary_label, etc.)
   └─> Entity Extraction: labeled → article_entities
```

## Deployment Strategy

### Phase 1: Parallel Operation (No Breaking Changes)

Keep current continuous processor running, add dataset jobs:

1. Deploy updated processor image with feature flags (all disabled)
2. Deploy mizzou-extraction-job.yaml
3. Run mizzou-extraction-job alongside continuous processor
4. Monitor logs to verify no conflicts

### Phase 2: Gradual Migration

Migrate datasets one by one:

1. Disable Mizzou extraction in continuous processor (set `ENABLE_EXTRACTION=false`)
2. Run mizzou-discovery-job + mizzou-extraction-job
3. Monitor for 24-48 hours
4. Repeat for other datasets

### Phase 3: Final Cleanup

Remove legacy code:

1. Remove discovery logic from continuous processor
2. Remove extraction logic from continuous processor
3. Update documentation
4. Archive old orchestration scripts

### Rollback Plan

If issues arise:

1. Re-enable extraction in continuous processor (`ENABLE_EXTRACTION=true`)
2. Stop dataset jobs
3. Revert processor deployment
4. All data remains intact (jobs write to same tables)

## Rate Limiting Examples

### Lehigh Valley (Aggressive Bot Detection)

```yaml
env:
  - name: INTER_REQUEST_MIN
    value: "90.0"   # 90 seconds minimum
  - name: INTER_REQUEST_MAX
    value: "180.0"  # 3 minutes maximum
  - name: BATCH_SLEEP_SECONDS
    value: "420.0"  # 7 minutes between batches
  - name: CAPTCHA_BACKOFF_BASE
    value: "7200"   # 2 hours base backoff
  - name: CAPTCHA_BACKOFF_MAX
    value: "21600"  # 6 hours max backoff
```

### Mizzou (Moderate Bot Protection)

```yaml
env:
  - name: INTER_REQUEST_MIN
    value: "5.0"    # 5 seconds minimum
  - name: INTER_REQUEST_MAX
    value: "15.0"   # 15 seconds maximum
  - name: BATCH_SLEEP_SECONDS
    value: "30.0"   # 30 seconds between batches
  - name: CAPTCHA_BACKOFF_BASE
    value: "1800"   # 30 minutes base backoff
  - name: CAPTCHA_BACKOFF_MAX
    value: "7200"   # 2 hours max backoff
```

## Creating Jobs for New Datasets

### 1. Discovery Job

Copy and customize the template:

```bash
cp k8s/templates/dataset-discovery-job.yaml k8s/mydataset-discovery-job.yaml
```

Replace placeholders:
- `DATASET_SLUG` → your dataset identifier
- `PROCESSOR_IMAGE` → latest processor image
- Adjust `--max-articles` and `--days-back` as needed

### 2. Extraction Job

Copy and customize the template:

```bash
cp k8s/templates/dataset-extraction-job.yaml k8s/mydataset-extraction-job.yaml
```

Replace placeholders:
- `DATASET_SLUG` → your dataset identifier
- `PROCESSOR_IMAGE` → latest processor image
- Adjust `--limit` and `--batches` for throughput
- Configure rate limiting based on site behavior

### 3. Deploy

```bash
kubectl apply -f k8s/mydataset-discovery-job.yaml
kubectl apply -f k8s/mydataset-extraction-job.yaml
```

### 4. Monitor

```bash
# Watch logs
kubectl logs -n production -l dataset=YOUR_DATASET --follow

# Check job status
kubectl get jobs -n production -l dataset=YOUR_DATASET

# Check pod status
kubectl get pods -n production -l dataset=YOUR_DATASET
```

## Scheduling Discovery Jobs

For regular discovery runs, convert jobs to CronJobs:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: mizzou-discovery-daily
spec:
  schedule: "0 6 * * *"  # Daily at 6 AM UTC
  jobTemplate:
    spec:
      # Same as Job spec
      template:
        # ...
```

## Monitoring

### Per-Dataset Metrics

```bash
# View logs for specific dataset
kubectl logs -n production -l dataset=Mizzou --follow

# List all extraction jobs
kubectl get jobs -n production -l type=extraction

# List all discovery jobs
kubectl get jobs -n production -l type=discovery

# Check continuous processor status
kubectl logs -n production -l app=mizzou-processor --follow
```

### Database Queries

```sql
-- Count articles by dataset
SELECT d.slug, COUNT(a.id) as article_count
FROM datasets d
JOIN dataset_sources ds ON d.id = ds.dataset_id
JOIN sources s ON ds.source_id = s.id
JOIN candidate_links cl ON s.host = cl.source
JOIN articles a ON cl.id = a.candidate_link_id
GROUP BY d.slug;

-- Check pipeline status by dataset
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

## Troubleshooting

### Job Not Starting

Check pod events:

```bash
kubectl describe job extract-mizzou -n production
kubectl get pods -n production -l dataset=Mizzou
```

### CAPTCHA Backoff Too Frequent

Increase rate limiting:

```yaml
- name: INTER_REQUEST_MIN
  value: "60.0"  # Increase from 5 to 60 seconds
- name: INTER_REQUEST_MAX
  value: "120.0"  # Increase from 15 to 120 seconds
```

### Out of Memory

Increase resource limits:

```yaml
resources:
  limits:
    memory: 4Gi  # Increase from 3Gi
```

### Job Takes Too Long

Reduce batch size or increase batches:

```yaml
command:
  - --limit
  - "10"   # Reduce from 20
  - --batches
  - "120"  # Increase from 60
```

## Related Documentation

- [Issue #77](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/77) - Original refactoring issue
- [k8s/templates/README.md](../k8s/templates/README.md) - Job templates documentation
- [CUSTOM_SOURCELIST_README.md](../CUSTOM_SOURCELIST_README.md) - Custom dataset workflow

## Future Enhancements

- [ ] Auto-scaling based on queue depth
- [ ] Automatic job triggering when URLs are ready
- [ ] Per-dataset resource quotas
- [ ] Advanced monitoring dashboards
- [ ] Automatic rate limit adjustment based on errors
