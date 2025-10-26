# Custom Source List Workflow

## Overview

This workflow allows you to process articles from a **separate source list** that is completely **isolated from Missouri records**. It provides a full pipeline including:

- ✅ Gazetteer creation
- ✅ Content extraction  
- ✅ Byline cleaning
- ✅ Wire/opinion detection
- ✅ ML classification
- ✅ Excel export with all metadata

**Key Feature:** These records will **never** be included in regular discovery cron jobs because they are tagged with a unique dataset identifier.

## Architecture

The system uses the existing **Dataset** model to create logical separations:

```
Dataset (special-project-2025)
    └── Source (example.com)
         └── CandidateLinks (your URLs)
              └── Articles (extracted content)
```

All CLI commands support `--dataset` filtering, so you can operate on your custom source list without touching Missouri records.

## Quick Start

### Step 1: Create Dataset and Source

```bash
python scripts/custom_sourcelist_workflow.py create-dataset \
    --name "Special Project 2025" \
    --slug "special-project-2025" \
    --source-url "https://example.com" \
    --source-name "Example Publisher"
```

**What this does:**
- Creates a `Dataset` record with slug `special-project-2025`
- Creates a `Source` record for `example.com`
- Links them together via `DatasetSource`
- Sets `is_public=False` to keep it private

### Step 2: Import URLs

Create a text file with URLs (one per line):

```
# urls.txt
https://example.com/article-1
https://example.com/article-2
https://example.com/article-3
```

Or use CSV format:

```csv
url
https://example.com/article-1
https://example.com/article-2
```

Import the URLs:

```bash
python scripts/custom_sourcelist_workflow.py import-urls \
    --dataset-slug "special-project-2025" \
    --urls-file urls.txt \
    --priority 10
```

**What this does:**
- Normalizes each URL
- Creates `CandidateLink` records with `dataset_id` linkage
- Sets `status='discovered'` (ready for extraction)
- Skips duplicate URLs automatically

### Step 3: Run Extraction Pipeline

```bash
python scripts/custom_sourcelist_workflow.py extract \
    --dataset-slug "special-project-2025" \
    --max-articles 100 \
    --extraction-limit 10 \
    --extraction-batches 5
```

**What this does:**
1. **Extract** - Downloads and parses article content using newspaper4k
2. **Clean** - Normalizes bylines/authors
3. **Detect Wire** - Identifies wire service articles (AP, Reuters, etc.)
4. **Classify** - Applies ML topic classification

All operations are filtered to **only** your dataset using `--dataset special-project-2025`.

### Step 4: Export to Excel

```bash
python scripts/custom_sourcelist_workflow.py export \
    --dataset-slug "special-project-2025" \
    --output results.xlsx
```

**Output columns:**
- Title
- Author  
- URL
- Publish Date
- Article Body (full text)
- Primary Classification
- Primary Confidence
- Secondary Classification
- Secondary Confidence
- Status
- Wire Service (if applicable)
- Source Name
- Extracted At
- Discovered At

## Isolation Guarantees

### How It Works

Your custom source list is **completely isolated** from Missouri records through:

1. **Dataset Tagging**: Every `CandidateLink` has `dataset_id='<your-dataset-id>'`
2. **CLI Filtering**: All commands support `--dataset` flag
3. **Database Queries**: Joins on `dataset_id` ensure separation

### Missouri Cron Jobs

Your Missouri discovery cron jobs should look like:

```bash
# Missouri-only discovery (no dataset filter)
python -m src.cli.main discover-urls --source-limit 50

# OR with explicit Missouri dataset
python -m src.cli.main discover-urls --dataset missouri-sources --source-limit 50
```

As long as you **never use** `--dataset special-project-2025` in your cron jobs, your custom articles will never be processed.

### Verification

To verify isolation, check the database:

```bash
# Count articles by dataset
kubectl exec -n production deployment/mizzou-processor -- python3 -c "
from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
session = db.get_session().__enter__()

result = session.execute(text('''
    SELECT 
        COALESCE(c.dataset_id, 'none') as dataset,
        COUNT(*) as count
    FROM articles a
    JOIN candidate_links c ON a.candidate_link_id = c.id
    GROUP BY c.dataset_id
''')).fetchall()

for row in result:
    print(f'{row[0]}: {row[1]} articles')
"
```

## Advanced Usage

### Custom Gazetteer

If you need location-specific entity matching:

```bash
# Create gazetteer for your source
python scripts/populate_gazetteer.py \
    --dataset-slug special-project-2025 \
    --source-id <source-id-from-step-1>
```

This will:
- Query OSM for locations near your source
- Populate gazetteer table with places, businesses, schools, etc.
- Enable entity extraction to find local references

### Re-extraction

If extraction fails or you want to re-process:

```bash
# Reset articles to allow re-extraction
python scripts/reset_extracted_articles.py \
    --dataset special-project-2025

# Run extraction again
python scripts/custom_sourcelist_workflow.py extract \
    --dataset-slug special-project-2025 \
    --max-articles 100
```

### Batch Import

For large URL lists, consider batching:

```bash
# Split large file into chunks
split -l 1000 urls.txt urls_batch_

# Import each batch
for file in urls_batch_*; do
    python scripts/custom_sourcelist_workflow.py import-urls \
        --dataset-slug special-project-2025 \
        --urls-file $file
done
```

## Database Schema

### Relationships

```sql
-- Dataset table
CREATE TABLE datasets (
    id TEXT PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    label TEXT NOT NULL,
    is_public BOOLEAN DEFAULT FALSE
);

-- Source table  
CREATE TABLE sources (
    id TEXT PRIMARY KEY,
    host TEXT NOT NULL,
    host_norm TEXT UNIQUE NOT NULL,
    canonical_name TEXT,
    status TEXT DEFAULT 'active'
);

-- Dataset-Source link
CREATE TABLE dataset_sources (
    id TEXT PRIMARY KEY,
    dataset_id TEXT REFERENCES datasets(id),
    source_id TEXT REFERENCES sources(id),
    UNIQUE(dataset_id, source_id)
);

-- Candidate links (your URLs)
CREATE TABLE candidate_links (
    id TEXT PRIMARY KEY,
    url TEXT UNIQUE NOT NULL,
    dataset_id TEXT REFERENCES datasets(id),
    source_id TEXT REFERENCES sources(id),
    status TEXT DEFAULT 'discovered',
    discovered_by TEXT,
    priority INTEGER DEFAULT 1
);

-- Articles (extracted content)
CREATE TABLE articles (
    id TEXT PRIMARY KEY,
    candidate_link_id TEXT REFERENCES candidate_links(id),
    title TEXT,
    author TEXT,
    content TEXT,
    primary_label TEXT,
    primary_label_confidence REAL,
    alternate_label TEXT,
    alternate_label_confidence REAL,
    wire JSON,
    status TEXT DEFAULT 'extracted'
);
```

### Query Examples

```sql
-- Find all articles from your dataset
SELECT a.title, a.author, a.url
FROM articles a
JOIN candidate_links c ON a.candidate_link_id = c.id
WHERE c.dataset_id = (SELECT id FROM datasets WHERE slug = 'special-project-2025');

-- Count articles by status
SELECT a.status, COUNT(*) 
FROM articles a
JOIN candidate_links c ON a.candidate_link_id = c.id
WHERE c.dataset_id = (SELECT id FROM datasets WHERE slug = 'special-project-2025')
GROUP BY a.status;

-- Find wire service articles
SELECT a.title, a.wire
FROM articles a  
JOIN candidate_links c ON a.candidate_link_id = c.id
WHERE c.dataset_id = (SELECT id FROM datasets WHERE slug = 'special-project-2025')
  AND a.wire IS NOT NULL;
```

## Troubleshooting

### URLs Not Importing

**Problem**: URLs are skipped during import

**Solution**: Check if URLs already exist:

```bash
kubectl exec -n production deployment/mizzou-processor -- python3 -c "
from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
session = db.get_session().__enter__()

url = 'https://example.com/article-1'
result = session.execute(
    text('SELECT id, status, dataset_id FROM candidate_links WHERE url = :url'),
    {'url': url}
).fetchone()

print(f'URL found: {result}')
"
```

### Extraction Failing

**Problem**: Articles not extracting

**Check 1**: Verify URLs are in correct status:

```bash
kubectl exec -n production deployment/mizzou-processor -- python3 -c "
from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
session = db.get_session().__enter__()

result = session.execute(text('''
    SELECT status, COUNT(*) 
    FROM candidate_links 
    WHERE dataset_id = (SELECT id FROM datasets WHERE slug = 'special-project-2025')
    GROUP BY status
''')).fetchall()

for row in result:
    print(f'{row[0]}: {row[1]}')
"
```

**Check 2**: Look for error messages:

```bash
kubectl logs -n production deployment/mizzou-processor --tail=100 | grep special-project
```

### Missing Classifications

**Problem**: Articles extracted but no ML labels

**Solution**: Ensure ML models are loaded:

```bash
# Check model availability
python -m src.cli.main classify --help

# Re-run classification
python -m src.cli.main classify \
    --dataset special-project-2025 \
    --limit 100
```

## Integration with Existing Workflows

### Adding to Orchestration Pipeline

If you want to automate this workflow, create a separate script:

```bash
#!/bin/bash
# scripts/run_custom_sourcelist.sh

DATASET="special-project-2025"

echo "🔄 Processing custom source list: $DATASET"

# Import any new URLs (if you have a growing list)
if [ -f "data/new_urls.txt" ]; then
    python scripts/custom_sourcelist_workflow.py import-urls \
        --dataset-slug "$DATASET" \
        --urls-file data/new_urls.txt
fi

# Run extraction pipeline
python scripts/custom_sourcelist_workflow.py extract \
    --dataset-slug "$DATASET" \
    --max-articles 100

# Export results
python scripts/custom_sourcelist_workflow.py export \
    --dataset-slug "$DATASET" \
    --output "reports/custom_${DATASET}_$(date +%Y%m%d).xlsx"

echo "✅ Complete! Check reports/ directory for results."
```

### Kubernetes CronJob

Deploy as a separate Kubernetes CronJob:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: custom-sourcelist-processor
  namespace: production
spec:
  schedule: "0 6 * * *"  # Daily at 6 AM
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: processor
            image: gcr.io/your-project/processor:latest
            command:
            - /bin/bash
            - -c
            - |
              python scripts/custom_sourcelist_workflow.py extract \
                --dataset-slug special-project-2025 \
                --max-articles 100
          restartPolicy: OnFailure
```

## Performance Considerations

### Extraction Speed

- **Single article**: ~2-5 seconds
- **Batch of 10**: ~30 seconds  
- **100 articles**: ~5-10 minutes

### Database Size

Each article consumes approximately:
- **CandidateLink**: ~500 bytes
- **Article**: ~5-50 KB (depending on content length)
- **ML Results**: ~200 bytes

1000 articles ≈ 10-50 MB database growth

### Excel Export Limits

Excel has a 1,048,576 row limit. For datasets larger than ~1 million articles, consider:
- Exporting in batches
- Using CSV format instead
- Filtering by date range or classification

## Best Practices

1. **Use Descriptive Slugs**: `client-project-2025` not `project1`
2. **Document Metadata**: Add description when creating dataset
3. **Track Imports**: Keep original URL lists for audit trail
4. **Regular Exports**: Export periodically during long-running extractions
5. **Monitor Errors**: Check logs after extraction for failed articles
6. **Backup Before Re-extraction**: Export before running reset scripts

## Support

For issues or questions:
1. Check logs: `kubectl logs -n production deployment/mizzou-processor`
2. Review database: Use SQL queries above
3. Contact: [Your contact info]

## Changelog

- **2025-10-11**: Initial implementation with full pipeline support
