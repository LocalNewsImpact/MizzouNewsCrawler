# All Predictions Storage for Article Classification

## Overview

As of migration `c50ba0e981d0`, the `article_labels` table now stores **all** classifier predictions with confidence scores, not just the top 2.

## Database Schema

### New Column

- **`all_predictions`** (JSONB): Stores all classifier predictions as a JSON array
  - Format: `[{"label": "label_name", "score": 0.xxxx}, ...]`
  - Indexed with GIN for fast queries
  - Only populated for **new** classifications after migration

### Existing Columns (unchanged)

- `primary_label` / `primary_label_confidence`: Top prediction
- `alternate_label` / `alternate_label_confidence`: Second prediction
- `meta`: Full metadata including timestamps

## Migration

Applied automatically in production when code is deployed:

```bash
# Migration file
alembic/versions/c50ba0e981d0_add_all_predictions_jsonb_to_article_.py

# To apply manually in production (via API pod)
kubectl exec -n production deployment/mizzou-api -- alembic upgrade head
```

## Usage

### Query All Predictions

**From local machine:**

```bash
# Get recent articles with all predictions
./query_all_predictions.py --limit 20

# Get specific articles
./query_all_predictions.py --article-ids "uuid1" "uuid2" "uuid3"
```

**From production (kubectl exec):**

```bash
kubectl cp query_all_predictions.py production/mizzou-api-POD:/tmp/
kubectl exec -n production mizzou-api-POD -- python /tmp/query_all_predictions.py --limit 5
```

### SQL Query Examples

**Get articles with specific confidence thresholds:**

```sql
SELECT 
    a.title,
    al.primary_label,
    al.all_predictions
FROM articles a
JOIN article_labels al ON a.id = al.article_id
WHERE al.all_predictions IS NOT NULL
  AND al.all_predictions @> '[{"label": "crime"}]'::jsonb
  AND (al.all_predictions -> 0 -> 'score')::float > 0.8
ORDER BY a.extracted_at DESC
LIMIT 10;
```

**Find articles where top 2 predictions are close:**

```sql
SELECT 
    a.id,
    a.title,
    al.primary_label,
    al.primary_label_confidence as top1,
    al.alternate_label,
    al.alternate_label_confidence as top2,
    (al.primary_label_confidence - al.alternate_label_confidence) as confidence_gap
FROM articles a
JOIN article_labels al ON a.id = al.article_id
WHERE al.all_predictions IS NOT NULL
  AND al.alternate_label_confidence IS NOT NULL
  AND (al.primary_label_confidence - al.alternate_label_confidence) < 0.1
ORDER BY confidence_gap ASC
LIMIT 20;
```

**Get all labels considered for an article:**

```sql
SELECT 
    jsonb_array_elements(all_predictions) -> 'label' as label,
    jsonb_array_elements(all_predictions) -> 'score' as score
FROM article_labels
WHERE article_id = 'YOUR_ARTICLE_ID'
ORDER BY (jsonb_array_elements(all_predictions) -> 'score')::float DESC;
```

## Code Flow

1. **Classification Service** (`src/services/classification_service.py`):
   - Calls `classifier.predict_batch(texts, top_k=10)` (or configurable top_k)
   - Creates metadata dict with `metadata["top_k"] = [pred.as_dict() for pred in predictions]`

2. **Database Save** (`src/models/database.py:save_article_classification`):
   - Extracts `all_predictions = metadata.get("top_k")`
   - Saves to `ArticleLabel.all_predictions` JSONB column

3. **Model** (`src/models/__init__.py:ArticleLabel`):
   - Now includes `all_predictions: Mapped[dict | None] = mapped_column(JSON)`

## Configuration

The number of predictions stored is controlled by the `top_k` parameter in classification:

```python
# Default: stores top 10 predictions
classifier.predict_batch(texts, top_k=10)

# To store more/fewer:
classifier.predict_batch(texts, top_k=20)  # All 20 CIN categories
```

## Backward Compatibility

- **Old articles**: `all_predictions` will be NULL (classified before migration)
- **New articles**: `all_predictions` populated automatically
- No need to reclassify old articles unless specifically needed
- Top 2 predictions still available in dedicated columns for fast queries

## Performance Notes

- GIN index allows efficient queries on JSONB content
- Queries on top 2 labels should use the dedicated columns (faster)
- Use `all_predictions` only when you need to analyze all confidence scores
