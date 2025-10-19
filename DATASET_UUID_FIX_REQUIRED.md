# Dataset ID Foreign Key Issue - CRITICAL BUG

## Problem

The `candidate_links.dataset_id` column contains **mixed data types**:
- Some rows have dataset **names** (strings like "Mizzou Missouri State")
- Some rows have dataset **slugs** (strings like "Mizzou-Missouri-State") 
- Some rows should have dataset **UUIDs** (like "61ccd4d3-763f-4cc6-b85d-74b268e80a00")

This causes:
- ❌ Extraction fails because slug lookup doesn't match name stored in dataset_id
- ❌ Data integrity issues - foreign key not enforced
- ❌ Fragile queries that break with spaces, hyphens, special characters
- ❌ 177 articles sat unextracted for hours due to this bug

## Root Cause

The Argo workflow and CLI commands accept dataset **names/slugs** as parameters but store them directly in `dataset_id` without resolving to the UUID first.

**Example from today:**
```python
# Argo passes:
--dataset "Mizzou Missouri State"  # NAME (with spaces)

# Database has:
datasets.slug = "Mizzou-Missouri-State"  # SLUG (with hyphens)
datasets.id = "61ccd4d3-763f-4cc6-b85d-74b268e80a00"  # UUID

# candidate_links stores:
dataset_id = "Mizzou Missouri State"  # WRONG! Should be UUID

# Extraction query fails:
WHERE dataset_id = (SELECT id FROM datasets WHERE slug = 'Mizzou Missouri State')
# Returns NULL because slug doesn't match
```

## Correct Design

### 1. CLI Layer (User-Facing)
- Accept human-readable names/slugs: `--dataset "Missouri State News"`
- Display human-readable names in output
- Keep names/slugs for user convenience

### 2. Application Layer (Resolution)
- **Immediately resolve** name/slug → UUID before ANY database operation
- Fail fast if dataset doesn't exist
- Add helper function: `resolve_dataset_id(name_or_slug_or_uuid) -> uuid`

### 3. Database Layer (Storage)
- **Only store UUIDs** in foreign key columns (`dataset_id`, `source_id`, etc.)
- Use UUIDs for all JOIN operations
- Enforce foreign key constraints properly

## Required Fixes

### 1. Add Dataset Resolution Helper
```python
# src/models/database.py or src/utils/dataset_utils.py

def resolve_dataset_id(
    engine, 
    dataset_identifier: str | None
) -> str | None:
    """Resolve dataset name, slug, or UUID to canonical UUID.
    
    Args:
        dataset_identifier: Name, slug, or UUID of dataset
        
    Returns:
        Dataset UUID or None if not found
        
    Raises:
        ValueError: If identifier provided but dataset not found
    """
    if not dataset_identifier:
        return None
        
    # Check if already a UUID
    try:
        uuid.UUID(dataset_identifier)
        return dataset_identifier  # Already a UUID
    except ValueError:
        pass
    
    # Try to find by slug or name
    with engine.connect() as conn:
        result = conn.execute(text('''
            SELECT id FROM datasets 
            WHERE slug = :identifier OR name = :identifier
            LIMIT 1
        '''), {'identifier': dataset_identifier})
        
        row = result.fetchone()
        if row:
            return str(row[0])
        
    raise ValueError(f"Dataset not found: {dataset_identifier}")
```

### 2. Update Discovery Command
```python
# src/cli/commands/discovery.py

def handle_discovery_command(args):
    db = DatabaseManager()
    
    # Resolve dataset to UUID FIRST
    dataset_uuid = None
    if args.dataset:
        dataset_uuid = resolve_dataset_id(db.engine, args.dataset)
        logger.info(f"Resolved dataset '{args.dataset}' to UUID: {dataset_uuid}")
    
    # Pass UUID to discovery, not name/slug
    discovery = NewsDiscovery(database_url=db.database_url)
    results = discovery.discover_sources(
        ...
        dataset_id=dataset_uuid,  # UUID, not name
        ...
    )
```

### 3. Update Extraction Command
```python
# src/cli/commands/extraction.py

def handle_extraction_command(args):
    # Resolve dataset to UUID
    if args.dataset:
        dataset_uuid = resolve_dataset_id(db.engine, args.dataset)
        logger.info(f"Using dataset UUID: {dataset_uuid}")
        
        # Update query to use UUID directly
        q = q.replace(
            "WHERE cl.status = 'article'",
            "WHERE cl.status = 'article' AND cl.dataset_id = :dataset_id"
        )
        params["dataset_id"] = dataset_uuid  # UUID, not slug
```

### 4. Update Argo Workflow
```yaml
# Change parameter from name to slug (until resolution is added)
parameters:
  - name: dataset
    value: "Mizzou-Missouri-State"  # Use SLUG not NAME

# Better: Add dataset resolution in CLI so name works
```

### 5. Data Migration Script
```python
# scripts/fix_dataset_ids.py

"""Fix candidate_links.dataset_id to use UUIDs instead of names/slugs."""

from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()

with db.engine.connect() as conn:
    # Get all datasets
    datasets = conn.execute(text('SELECT id, name, slug FROM datasets')).fetchall()
    
    for dataset in datasets:
        dataset_id, name, slug = dataset
        
        # Update rows with name
        result = conn.execute(text('''
            UPDATE candidate_links 
            SET dataset_id = :uuid 
            WHERE dataset_id = :name
        '''), {'uuid': dataset_id, 'name': name})
        print(f"Updated {result.rowcount} rows with name '{name}' to UUID")
        
        # Update rows with slug  
        result = conn.execute(text('''
            UPDATE candidate_links 
            SET dataset_id = :uuid 
            WHERE dataset_id = :slug
        '''), {'uuid': dataset_id, 'slug': slug})
        print(f"Updated {result.rowcount} rows with slug '{slug}' to UUID")
    
    conn.commit()
```

## Immediate Workaround (Applied)

Fixed the Argo CronWorkflow to pass the correct slug:
```bash
kubectl patch cronworkflow mizzou-news-pipeline -n production --type='json' -p='[
  {
    "op": "replace",
    "path": "/spec/workflowSpec/templates/0/steps/0/0/arguments/parameters/0/value",
    "value": "Mizzou-Missouri-State"
  }
]'
```

Fixed candidate_links to use correct UUID:
```sql
UPDATE candidate_links 
SET dataset_id = '61ccd4d3-763f-4cc6-b85d-74b268e80a00'
WHERE dataset_id = 'Mizzou Missouri State'
```

## Testing Checklist

After implementing fixes:
- [ ] Discovery command resolves dataset name → UUID
- [ ] Extraction command resolves dataset name → UUID
- [ ] Verification command (if using dataset) resolves → UUID
- [ ] All candidate_links.dataset_id values are valid UUIDs
- [ ] Foreign key constraint can be added to candidate_links.dataset_id
- [ ] Argo workflow works with dataset name parameter
- [ ] Manual commands work with name, slug, or UUID
- [ ] Error handling when dataset doesn't exist

## Benefits

✅ **Data integrity** - proper foreign keys enforced  
✅ **No parsing issues** - UUIDs have no spaces/hyphens/special chars  
✅ **Flexibility** - Users can specify name, slug, or UUID  
✅ **Reliability** - Queries won't break due to naming changes  
✅ **Performance** - UUID joins are efficient  
✅ **Maintainability** - Single source of truth (UUID)  

---

**Priority**: CRITICAL - This bug caused 177 articles to fail extraction for hours
**Effort**: Medium - ~2-4 hours to implement properly with tests
**Risk**: Low - Backward compatible with proper resolution logic
