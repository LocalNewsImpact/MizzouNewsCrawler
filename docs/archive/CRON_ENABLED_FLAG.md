# Cron Enabled Flag Implementation

## Summary

Added `cron_enabled` flag to the Dataset model to **explicitly control which datasets are processed by automated cron jobs**. This prevents accidental inclusion of custom source lists (like Lehigh Valley) in Missouri processing jobs.

## Problem Solved

**Before:**
- Datasets were segregated by UUID at database level
- But extraction command without `--dataset` flag would process ALL articles with `status='article'`
- Risk: Missouri cron job could accidentally process Lehigh Valley articles

**After:**
- New `cron_enabled` boolean column on datasets table
- Default: `True` for existing datasets (maintains current behavior)
- Custom source lists: Set to `False` (excluded from cron by default)
- Extraction without `--dataset` flag: Only processes cron-enabled datasets

## Implementation

### 1. Database Schema Change

**File:** `src/models/__init__.py` (Dataset model)

```python
# Added to Dataset model
cron_enabled = Column(Boolean, default=True, nullable=False)
```

**Purpose:**
- `True` = Include in automated discovery/extraction jobs (Missouri datasets)
- `False` = Manual processing only (custom source lists like Lehigh Valley)

### 2. Migration

**File:** `alembic/versions/1c15007392b3_add_cron_enabled_flag_to_datasets.py`

```sql
-- Adds column with server_default='1' for existing datasets
ALTER TABLE datasets ADD COLUMN cron_enabled BOOLEAN NOT NULL DEFAULT 1;
```

**PostgreSQL/Cloud SQL compatible** - no SQLite-specific syntax

### 3. Custom Sourcelist Workflow Update

**File:** `scripts/custom_sourcelist_workflow.py` (line 119)

```python
dataset = Dataset(
    ...
    cron_enabled=False,  # Exclude from automated cron jobs by default
)
```

**Output when creating dataset:**
```
✓ Created dataset 'Penn-State-Lehigh' (ID: 3c4db976...)
  🔒 Cron disabled (manual processing only)
```

### 4. Extraction Command Protection

**File:** `src/cli/commands/extraction.py` (lines 258-273)

**Before:**
```python
if getattr(args, "dataset", None):
    # Filter by specific dataset
    ...
```

**After:**
```python
if getattr(args, "dataset", None):
    # Filter by specific dataset
    ...
else:
    # No explicit dataset - exclude cron-disabled datasets
    q = q.replace(
        "WHERE cl.status = 'article'",
        """WHERE cl.status = 'article'
        AND (cl.dataset_id IS NULL
             OR cl.dataset_id IN (
                 SELECT id FROM datasets WHERE cron_enabled = 1
             ))"""
    )
```

## Behavior

### Missouri Cron Jobs (No --dataset flag)

```bash
python -m src.cli.main extract --limit 50
```

**Query executed:**
```sql
SELECT ... FROM candidate_links cl
WHERE cl.status = 'article'
  AND (cl.dataset_id IS NULL 
       OR cl.dataset_id IN (SELECT id FROM datasets WHERE cron_enabled = 1))
```

**Result:** 
- ✅ Processes Missouri articles (dataset_id=NULL or cron_enabled=True datasets)
- ❌ **Excludes** Lehigh Valley (cron_enabled=False)

### Manual Lehigh Valley Processing

```bash
python -m src.cli.main extract --dataset Penn-State-Lehigh --limit 50
```

**Query executed:**
```sql
SELECT ... FROM candidate_links cl
WHERE cl.status = 'article'
  AND cl.dataset_id = (SELECT id FROM datasets WHERE slug = 'Penn-State-Lehigh')
```

**Result:**
- ✅ Processes ONLY Lehigh Valley articles
- Works regardless of cron_enabled value (explicit dataset override)

## Migration Path

### Existing Datasets

All existing datasets get `cron_enabled=True` by default:
- Missouri datasets: Continue being processed by cron jobs ✅
- No behavior change for existing workflows ✅

### New Custom Source Lists

Created via `custom_sourcelist_workflow.py`:
- Automatically set `cron_enabled=False`
- Must be processed manually with explicit `--dataset` flag
- Protected from accidental inclusion in cron jobs ✅

### Lehigh Valley Dataset

Updated locally:
```python
UPDATE datasets SET cron_enabled = False WHERE slug = 'Penn-State-Lehigh'
```

Will be automatically set on Cloud SQL after migration runs.

## Cloud SQL Deployment

### Migration Will Run Automatically

When processor pod starts with new code:
1. Alembic runs pending migrations
2. `cron_enabled` column added to datasets table
3. Existing datasets get `cron_enabled=TRUE`
4. New datasets from workflow get `cron_enabled=FALSE`

### Update Lehigh Valley After Deployment

```bash
kubectl exec -n production deployment/mizzou-processor -- python3 -c "
from src.models.database import DatabaseManager
from src.models import Dataset
from sqlalchemy import update

db = DatabaseManager()
with db.get_session() as session:
    session.execute(
        update(Dataset)
        .where(Dataset.slug == 'Penn-State-Lehigh')
        .values(cron_enabled=False)
    )
    session.commit()
    print('✓ Penn-State-Lehigh: cron_enabled=False')
"
```

## Verification

### Check Dataset Status

```bash
kubectl exec -n production deployment/mizzou-processor -- python3 -c "
from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
with db.get_session() as session:
    result = session.execute(text('''
        SELECT slug, cron_enabled, label
        FROM datasets
        ORDER BY slug
    ''')).fetchall()
    
    print('Dataset Status:')
    for row in result:
        status = '🔓 Cron enabled' if row[1] else '🔒 Cron disabled'
        print(f'  {row[0]}: {status}')
"
```

**Expected Output:**
```
Dataset Status:
  missouri-sources: 🔓 Cron enabled
  Penn-State-Lehigh: 🔒 Cron disabled
```

### Test Extraction Query

```bash
# Test what cron job would process
kubectl exec -n production deployment/mizzou-processor -- python3 -c "
from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
with db.get_session() as session:
    result = session.execute(text('''
        SELECT 
            COALESCE(d.slug, 'no-dataset') as dataset,
            COUNT(*) as count
        FROM candidate_links cl
        LEFT JOIN datasets d ON cl.dataset_id = d.id
        WHERE cl.status = 'article'
          AND (cl.dataset_id IS NULL 
               OR cl.dataset_id IN (SELECT id FROM datasets WHERE cron_enabled = 1))
        GROUP BY d.slug
    ''')).fetchall()
    
    print('Articles available to cron jobs:')
    for row in result:
        print(f'  {row[0]}: {row[1]} articles')
"
```

**Expected Output:**
```
Articles available to cron jobs:
  no-dataset: 15000 articles (Missouri)
  missouri-sources: 500 articles (if Missouri dataset exists)
  # Penn-State-Lehigh should NOT appear here
```

## Benefits

✅ **Explicit Control:** Clear flag indicates dataset's cron eligibility  
✅ **Safe Default:** New custom source lists automatically excluded  
✅ **Backward Compatible:** Existing datasets maintain current behavior  
✅ **No Implicit Logic:** No need to guess which datasets should be processed  
✅ **Override Available:** Explicit `--dataset` flag bypasses cron restriction  

## Documentation Updates

Updated files to explain cron_enabled flag:
- `CUSTOM_SOURCELIST_CSV_GUIDE.md` - Mention automatic cron disabling
- `CUSTOM_SOURCELIST_WORKFLOW.md` - Explain isolation mechanism
- `LEHIGH_VALLEY_DEPLOYMENT.md` - Document cron protection

## Testing Plan

1. **Deploy to Cloud SQL** - Migration runs automatically
2. **Verify flag exists** - Query datasets table
3. **Test Missouri cron** - Should NOT process Lehigh Valley
4. **Test explicit dataset** - Should process Lehigh Valley when specified
5. **Create new dataset** - Should get cron_enabled=False by default

## Rollback Plan

If needed to revert:

```bash
# Cloud SQL
kubectl exec -n production deployment/mizzou-processor -- python3 -c "
from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
with db.get_session() as session:
    session.execute(text('ALTER TABLE datasets DROP COLUMN cron_enabled'))
    session.commit()
    print('✓ Rolled back cron_enabled column')
"
```

Then revert code changes and redeploy.

## Summary

This change provides **explicit, database-level control** over which datasets participate in automated processing, eliminating the risk of accidentally mixing custom source lists with Missouri data in cron jobs.
