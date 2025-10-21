# Custom Source List Implementation

## Summary

Created a complete workflow for processing articles from a separate source list that is **isolated from Missouri records**. The system leverages the existing Dataset model to ensure complete separation.

## Files Created

### 1. Main Scripts
- **`scripts/custom_sourcelist_workflow.py`** - Complete workflow manager with 4 commands:
  - `create-dataset` - Initialize dataset and source
  - `import-urls` - Bulk import URLs from file
  - `extract` - Run full extraction pipeline
  - `export` - Generate Excel report

- **`scripts/launch_dataset_job.py`** - Kubernetes Job orchestration (NEW):
  - Launch isolated extraction jobs per dataset
  - Custom resource limits and batching
  - Automatic job cleanup after 24 hours
  - Dry-run mode for testing manifests
  - Independent logging with dataset labels

### 2. Documentation
- **`docs/CUSTOM_SOURCELIST_WORKFLOW.md`** - Comprehensive guide (500+ lines)
  - Architecture overview
  - Step-by-step instructions
  - Database schema
  - Troubleshooting
  - Best practices
  
- **`docs/CUSTOM_SOURCELIST_QUICKREF.md`** - Quick reference
  - One-command setup
  - Common tasks
  - Output columns
  - Integration examples

## How Isolation Works

The key to isolation is the **Dataset** model:

```
Dataset (slug='special-project')
    ↓
CandidateLink (dataset_id='<uuid>')
    ↓
Article (via candidate_link_id)
```

All CLI commands support `--dataset` filtering:
- `discover-urls --dataset missouri` ← Missouri cron jobs
- `extract --dataset special-project` ← Your custom project

**As long as you never use your custom dataset slug in cron jobs, the records remain isolated.**

## Complete Workflow

### Local/Manual Processing

```bash
# 1. Setup (one time)
python scripts/custom_sourcelist_workflow.py create-dataset \
    --name "Client Project 2025" \
    --slug "client-project-2025" \
    --source-url "https://example.com" \
    --source-name "Example Publisher"

# 2. Import URLs
python scripts/custom_sourcelist_workflow.py import-urls \
    --dataset-slug "client-project-2025" \
    --urls-file urls.txt

# 3. Process
python scripts/custom_sourcelist_workflow.py extract \
    --dataset-slug "client-project-2025" \
    --max-articles 100

# 4. Export
python scripts/custom_sourcelist_workflow.py export \
    --dataset-slug "client-project-2025" \
    --output results.xlsx
```

### Kubernetes Job Processing (Recommended for Large Datasets)

For datasets with hundreds or thousands of URLs, use the Kubernetes Job launcher for better isolation and resource management:

```bash
# 1. Setup and import URLs (same as above)
python scripts/custom_sourcelist_workflow.py create-dataset ...
python scripts/custom_sourcelist_workflow.py import-urls ...

# 2. Launch isolated extraction job in Kubernetes
python scripts/launch_dataset_job.py \
    --dataset "client-project-2025" \
    --batches 60 \
    --limit 20

# 3. Monitor job progress
kubectl logs -n production -l dataset=client-project-2025 --follow

# 4. Check job status
kubectl get job extract-client-project-2025 -n production

# 5. Export results (after job completes)
python scripts/custom_sourcelist_workflow.py export \
    --dataset-slug "client-project-2025" \
    --output results.xlsx
```

**Benefits of Kubernetes Jobs:**
- ✅ Isolated pod per dataset (failures don't affect other jobs)
- ✅ Independent logging with dataset labels
- ✅ Custom resource limits per dataset
- ✅ Parallel processing of multiple datasets
- ✅ Automatic cleanup after 24 hours
- ✅ No interference with Missouri continuous processor

## What Each Step Does

### Extract Pipeline

The `extract` command runs a **full pipeline**:

1. **Extraction** - Downloads HTML, parses with newspaper4k
2. **Cleaning** - Normalizes bylines/authors  
3. **Wire Detection** - Identifies AP, Reuters, etc.
4. **ML Classification** - Topic classification (primary + secondary)

### Excel Export

Output includes:
- Title, Author, URL, Publish Date
- **Full article body text**
- Primary/Secondary ML classifications with confidence scores
- Wire service attribution
- Processing metadata

## Job Launcher Details

The `launch_dataset_job.py` script creates Kubernetes Jobs dynamically:

### Usage Examples

```bash
# Test with dry-run (see the manifest without applying)
python scripts/launch_dataset_job.py \
    --dataset client-project-2025 \
    --batches 60 \
    --dry-run

# Launch with default settings (60 batches × 20 articles)
python scripts/launch_dataset_job.py \
    --dataset client-project-2025 \
    --batches 60

# Large dataset with more resources
python scripts/launch_dataset_job.py \
    --dataset large-dataset \
    --batches 100 \
    --limit 50 \
    --cpu-request 500m \
    --memory-request 2Gi \
    --memory-limit 4Gi

# Custom image version
python scripts/launch_dataset_job.py \
    --dataset test-dataset \
    --batches 10 \
    --image us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:v1.2.3
```

### Monitoring Jobs

```bash
# Watch live logs
kubectl logs -n production -l dataset=client-project-2025 --follow

# Check job status
kubectl get job extract-client-project-2025 -n production

# Detailed job information
kubectl describe job extract-client-project-2025 -n production

# List all extraction jobs
kubectl get jobs -n production -l type=extraction

# Delete a job manually (if needed)
kubectl delete job extract-client-project-2025 -n production
```

### Job Features

- **Automatic Cleanup**: Jobs are deleted 24 hours after completion (configurable with `--ttl-seconds`)
- **Resource Limits**: Prevents runaway resource usage
- **Failure Isolation**: Failed jobs don't affect other datasets
- **Restart Policy**: `Never` - jobs won't restart on failure (check logs for debugging)
- **Labels**: Easy filtering by dataset, type, or app name

## Gazetteer Support

For location-based entity extraction:

```bash
# Create gazetteer for source (optional)
python scripts/populate_gazetteer.py \
    --dataset-slug client-project-2025 \
    --source-id <source-id-from-create-dataset>
```

This will:
- Query OSM for places near the source
- Enable entity extraction to find local references
- Match article mentions to gazetteer entries

## Database Verification

Check isolation:

```bash
kubectl exec -n production deployment/mizzou-processor -- python3 -c "
from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
session = db.get_session().__enter__()

# Count articles by dataset
result = session.execute(text('''
    SELECT 
        COALESCE(d.slug, 'no-dataset') as dataset,
        COUNT(*) as count
    FROM articles a
    JOIN candidate_links c ON a.candidate_link_id = c.id
    LEFT JOIN datasets d ON c.dataset_id = d.id
    GROUP BY c.dataset_id, d.slug
    ORDER BY count DESC
''')).fetchall()

for row in result:
    print(f'{row[0]}: {row[1]} articles')
"
```

## Missouri Cron Job Protection

Your existing Missouri cron jobs are **automatically protected** because:

1. They don't specify `--dataset` flag → processes all sources without dataset_id
2. OR they specify `--dataset missouri` → only processes Missouri dataset
3. Custom articles have `dataset_id='<your-uuid>'` → never match

To be extra safe, always use explicit dataset filters:

```bash
# Good: Explicit Missouri filter
python -m src.cli.main discover-urls --dataset missouri --source-limit 50

# Also safe: No filter processes only records without dataset_id
python -m src.cli.main discover-urls --source-limit 50

# Never do this:
python -m src.cli.main discover-urls --dataset client-project-2025  # ← Would process custom list
```

## Advantages of This Approach

✅ **Uses Existing Infrastructure**: Leverages Dataset model, CLI filters, pipeline  
✅ **No Code Changes Needed**: Existing commands already support `--dataset`  
✅ **Complete Isolation**: Database-level separation via dataset_id  
✅ **Full Feature Set**: Extraction, cleaning, wire detection, ML classification  
✅ **Excel Export**: Built-in reporting with all requested fields  
✅ **Reusable**: Same dataset can handle multiple URL imports  
✅ **Auditable**: Full database tracking and metadata  

## Testing Checklist

Before production use:

- [ ] Create test dataset with unique slug
- [ ] Import 5-10 test URLs
- [ ] Run extraction pipeline
- [ ] Verify Excel export has all columns
- [ ] Check Missouri discovery still works
- [ ] Confirm test dataset not in Missouri queries

## Next Steps

1. **Review Documentation**: Read `docs/CUSTOM_SOURCELIST_WORKFLOW.md`
2. **Test Locally**: Try with small dataset first
3. **Deploy to Production**: Use script with real URLs
4. **Set Up Automation**: Add to cron or Kubernetes CronJob if needed
5. **Monitor**: Check logs and database after first run

## Support

For questions or issues:
- Check `docs/CUSTOM_SOURCELIST_WORKFLOW.md` troubleshooting section
- Review database queries in documentation
- Examine logs: `kubectl logs deployment/mizzou-processor`

## Implementation Notes

- Script is Python 3.11+ compatible
- Uses existing DatabaseManager and models
- Follows project code style (black, flake8 compliant)
- No external dependencies beyond existing requirements
- Handles errors gracefully with informative messages
