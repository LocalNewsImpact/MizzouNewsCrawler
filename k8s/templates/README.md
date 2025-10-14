# Kubernetes Job Templates

This directory contains reusable Kubernetes manifest templates for dataset-specific jobs.
These templates enable independent orchestration of discovery and extraction per dataset,
allowing for better rate limiting, monitoring, and CAPTCHA backoff isolation.

## Architecture

After refactoring (Issue #77), pipeline steps are split:

**Dataset-Specific Jobs** (external site interaction):
- Discovery: Find article URLs from RSS/sitemaps
- Extraction: Fetch and extract article content

**Continuous Processor** (internal processing):
- Cleaning: Clean extracted content
- ML Analysis: Classify articles
- Entity Extraction: Extract location entities

## Files

### `dataset-discovery-job.yaml`

Template for launching isolated discovery jobs for specific datasets.
Discovery finds new article URLs from RSS feeds, sitemaps, and homepages.

### `dataset-extraction-job.yaml`

Template for launching isolated extraction jobs for specific datasets.
Extraction fetches articles and extracts title, content, author, etc.

**Usage:**

Instead of manually editing this template, use the automated script:

```bash
python scripts/launch_dataset_job.py --dataset YOUR_DATASET --batches 60 --limit 20
```

**Manual Usage (if needed):**

1. Copy the template
2. Replace placeholders:
   - `DATASET_SLUG` - Your dataset identifier
   - `PROCESSOR_IMAGE` - Full image path (e.g., `us-central1-docker.pkg.dev/...`)
3. Apply to cluster:
   ```bash
   kubectl apply -f your-job.yaml
   ```

**Placeholders:**

- `DATASET_SLUG` - Dataset slug from the `datasets` table
- `PROCESSOR_IMAGE` - Container image to use
- `extract-dataset_slug` - Job name (lowercase, hyphenated)

**Labels:**

All jobs include labels for easy filtering:
- `dataset: DATASET_SLUG` - Filter by dataset
- `type: extraction` - Filter by job type
- `app: extract-DATASET_SLUG` - Application identifier

**Monitoring:**

```bash
# Watch logs
kubectl logs -n production -l dataset=YOUR_DATASET --follow

# Check status
kubectl get job extract-YOUR_DATASET -n production

# List all extraction jobs
kubectl get jobs -n production -l type=extraction
```

## Best Practices

1. **Use the script**: `scripts/launch_dataset_job.py` is the recommended way to launch jobs
2. **Dry-run first**: Always test with `--dry-run` before applying
3. **Monitor resources**: Check CPU/memory usage and adjust limits as needed
4. **Check logs**: Monitor job logs for errors or issues
5. **Clean up**: Jobs auto-delete after 24 hours (configurable with TTL)

## Custom Resource Limits

For datasets requiring more resources:

```bash
python scripts/launch_dataset_job.py \
    --dataset large-dataset \
    --batches 100 \
    --cpu-request 1000m \
    --cpu-limit 2000m \
    --memory-request 2Gi \
    --memory-limit 4Gi
```

## Troubleshooting

### Job Not Starting

Check pod events:
```bash
kubectl describe job extract-YOUR_DATASET -n production
kubectl get pods -n production -l dataset=YOUR_DATASET
```

### Out of Memory

Increase memory limits:
```bash
python scripts/launch_dataset_job.py \
    --dataset YOUR_DATASET \
    --memory-limit 4Gi \
    --batches 60
```

### Job Takes Too Long

Increase parallelism or reduce batch size:
```bash
python scripts/launch_dataset_job.py \
    --dataset YOUR_DATASET \
    --batches 100 \
    --limit 10
```

## See Also

- `scripts/launch_dataset_job.py` - Job launcher script
- `CUSTOM_SOURCELIST_README.md` - Custom dataset workflow guide
- Issue #66 - Dataset-Specific Job Orchestration
