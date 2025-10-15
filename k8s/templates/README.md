# Kubernetes Job Templates

This directory contains reusable Kubernetes manifest templates for dataset-specific extraction jobs.

## Files

### `dataset-extraction-job.yaml`

Template for launching isolated extraction jobs for specific datasets.

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

### Single-Domain Datasets (Rate Limiting)

For datasets with only one domain (like Lehigh Valley News), the extraction system automatically:

1. **Detects single-domain datasets** before processing begins
2. **Applies conservative rate limiting** automatically between batches
3. **Warns if BATCH_SLEEP_SECONDS is too low** for single-domain scenarios

**What you'll see in logs:**
```
📊 Dataset analysis: 1 unique domain(s)
⚠️  Single-domain dataset detected: lehighvalleynews.com
🐌 Rate limiting will be conservative to avoid bot detection
```

**Recommended environment variables for single-domain datasets:**

```yaml
# In your job YAML or via launch_dataset_job.py
env:
  - name: BATCH_SLEEP_SECONDS
    value: "300"  # 5 minutes between batches (recommended for aggressive bot detection)
  - name: BATCH_SLEEP_JITTER
    value: "0.45"  # Add ±45% randomness to sleep time
  - name: INTER_REQUEST_MIN
    value: "90.0"  # Minimum 90 seconds between requests
  - name: INTER_REQUEST_MAX
    value: "180.0"  # Maximum 180 seconds between requests
```

**Why this matters:**
- Single-domain datasets can't rotate between domains to avoid rate limits
- Every request hits the same server, making bot detection more likely
- Conservative timing prevents 429 errors and IP blocks

**Monitoring single-domain jobs:**
```bash
# Watch for rate limit warnings
kubectl logs -n production -l dataset=YOUR_DATASET --follow | grep "rate limit\|Single-domain"

# Check batch sleep timing
kubectl logs -n production -l dataset=YOUR_DATASET --follow | grep "⏸️"
```

## See Also

- `scripts/launch_dataset_job.py` - Job launcher script
- `CUSTOM_SOURCELIST_README.md` - Custom dataset workflow guide
- Issue #66 - Dataset-Specific Job Orchestration
