# Cleanup of Failed Extractions - Summary

**Date:** October 13, 2025  
**Issue:** 606 articles appeared "pending" for ML analysis, but only 4 were actually eligible

## Root Cause Analysis

The "606 pending" count was misleading because it counted ALL articles with `primary_label IS NULL`, which included:
- **361 wire** articles (correctly excluded from ML classification)
- **76 obituary** articles (correctly excluded from ML classification)  
- **47 opinion** articles (correctly excluded from ML classification)
- **118 extracted** articles without content (failed extractions)
- **22 extracted** articles without content but WITH invalid article_labels
- **2 cleaned** articles ready for ML (normal state)

## Problem Identified

**140 articles** had `status='extracted'` but `content IS NULL` - these were failed extractions that got stuck in the pipeline:
- **22 articles** had invalid `article_labels` (labels created despite no content to classify)
- **118 articles** had no labels (correctly)

These articles needed to be:
1. Have their invalid labels removed
2. Be reset for re-extraction
3. Leverage the new 404 auto-detection feature (deployed in processor:d0c043e)

## Cleanup Actions Taken

### Step 1: Delete Invalid Article Labels
```sql
DELETE FROM article_labels
WHERE article_id IN (
    SELECT id FROM articles 
    WHERE status = 'extracted' AND content IS NULL
)
AND label_version = 'default'
```
**Result:** Deleted 22 invalid article_labels

### Step 2: Delete Failed Article Records
```sql
DELETE FROM articles 
WHERE status = 'extracted' AND content IS NULL
```
**Result:** Deleted 140 article records (22 with labels + 118 without)

### Step 3: Reset Candidate Links for Re-extraction
```sql
UPDATE candidate_links
SET status = 'article'
WHERE url IN (failed article URLs)
AND status = 'extracted'
```
**Result:** Reset 140 candidate_links from `extracted` to `article`

## Affected Domains

Top domains with failed extractions that will be retried:
- **www.kprs.com:** 32 articles
- **www.the-standard.org:** 26 articles
- **www.webstercountycitizen.com:** 15 articles
- **www.949kcmo.com:** 13 articles
- **www.koamnewsnow.com:** 11 articles
- **www.maryvilleforum.com:** 10 articles
- **www.ktts.com:** 8 articles
- **bocojo.com:** 7 articles
- **www.dddnews.com:** 5 articles
- **eldoradospringsmo.com:** 3 articles

## Final Pipeline Status

### Extraction Queue
- **426 candidate_links** with status=`article` (includes 140 reset links)
- Ready for re-extraction with automatic 404 detection

### Cleaning Queue  
- **0 articles** with status=`extracted` and content (clear)

### ML Analysis Queue
- **0 articles** with status=`cleaned` without labels (clear)

### "Pending" Articles (Not Actually Pending)
- **484 total** articles without primary_label:
  - **361 wire** - correctly excluded from ML
  - **76 obituary** - correctly excluded from ML
  - **47 opinion** - correctly excluded from ML

## Benefits of This Cleanup

1. **Removed invalid data**: 22 article_labels for articles without content
2. **Reset failed extractions**: 140 articles will be re-extracted
3. **Automatic 404 detection**: New feature (deployed in d0c043e) will catch and mark 404s
4. **Clear pipeline**: No articles stuck in invalid states
5. **Accurate metrics**: "Pending" count now reflects actual work needed

## Next Steps

The continuous processor will automatically:
1. Pick up the 426 articles ready for extraction (including 140 reset articles)
2. Extract content with newspaper4k, BeautifulSoup, and Selenium fallbacks
3. Detect 404/410 responses and automatically mark them with status='404'
4. Process successfully extracted articles through cleaning → ML classification → entity extraction

## Lessons Learned

1. **Better metrics needed**: The `analysis_pending` count should exclude wire/obituary/opinion statuses
2. **Validate content before labeling**: Articles should not receive ML labels if they have no content
3. **404 auto-detection crucial**: The new feature will prevent similar accumulation in the future
4. **Regular cleanup needed**: Periodic scans for articles with invalid states (extracted but no content)

## Recommended Improvements

1. Update `continuous_processor.py` line 79-84 to exclude wire/obituary/opinion from `analysis_pending` count
2. Add validation in classification service to skip articles without content
3. Create a scheduled cleanup job to detect and reset failed extractions
4. Add metrics/alerts for articles stuck in `extracted` status for > 24 hours
