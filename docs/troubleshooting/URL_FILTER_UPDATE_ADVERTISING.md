# URL Filter Update: Exclude Advertising and Promotional Pages

**Date**: October 20, 2025  
**Issue**: `https://www.dddnews.com/posterboard-ads/mcdonalds-10f2b30a` is not a story URL  
**Status**: ✅ FIXED

---

## Problem

The system was discovering and attempting to process advertising and promotional pages that are not news articles:

**Examples of problematic URLs:**
- `https://www.dddnews.com/posterboard-ads/mcdonalds-10f2b30a`
- `https://www.darnews.com/posterboard-ads/donut-house-bd68271e`
- `https://www.dddnews.com/posterboard-ads/common-ground-assembly-of-god-bb998a67`
- `https://www.darnews.com/posterboard-ads/godfathers-pizza-602155dc`

These URLs are:
- **Paid advertising content** (posterboard ads, classifieds, marketplace)
- **Not news articles**
- **Should be filtered out during discovery**

---

## Solution

### Files Modified

#### 1. `src/utils/url_classifier.py`

Added advertising/promotional patterns to `NON_ARTICLE_PATTERNS`:

```python
# Advertising and promotional pages
r"/posterboard-ads/",
r"/classifieds/",
r"/marketplace/",
r"/deals/",
r"/coupons/",
r"/promotions/",
r"/sponsored/",
```

**Impact**: Used by URL verification service during the verification phase to quickly filter non-articles.

#### 2. `src/crawler/__init__.py`

Added the same patterns to `_is_likely_article()` method's `skip_patterns`:

```python
skip_patterns = [
    # ... existing patterns ...
    "/posterboard-ads/",
    "/classifieds/",
    "/marketplace/",
    "/deals/",
    "/coupons/",
    "/promotions/",
    "/sponsored/",
]
```

**Impact**: Used during link discovery to skip these URLs before they enter the pipeline.

---

## Verification

### Test Results

```python
from src.utils.url_classifier import is_likely_article_url

# ❌ Filtered (correctly)
is_likely_article_url('https://www.dddnews.com/posterboard-ads/mcdonalds-10f2b30a')
# => False

is_likely_article_url('https://www.darnews.com/posterboard-ads/donut-house-bd68271e')
# => False

is_likely_article_url('https://www.dddnews.com/classifieds/item-123')
# => False

# ✅ Allowed (correctly)
is_likely_article_url('https://www.dddnews.com/news/local-story-12345')
# => True

is_likely_article_url('https://www.dddnews.com/article/real-news-story')
# => True
```

---

## Impact Assessment

### Where Filtering Happens

1. **Discovery Phase** (`src/crawler/__init__.py`)
   - Links discovered from RSS feeds and sitemaps
   - Filters applied during `_is_likely_article()` check
   - Prevents ad URLs from being saved to database

2. **Verification Phase** (`src/services/url_verification.py`)
   - Uses `src/utils/url_classifier.is_likely_article_url()`
   - Fast pattern matching before StorySniffer ML model
   - Reduces unnecessary HTTP requests and ML inference

### Existing Data

**Posterboard-ads URLs in database:**
- Found in multiple report files from September 2025
- Previously classified as "obituary" by content type detector (incorrect)
- Will no longer be discovered going forward

**Examples from reports:**
```
Delta Dunklin Democrat: https://www.dddnews.com/posterboard-ads/jimmy-clean-d7f14b8d
Delta Arkansas News: https://www.darnews.com/posterboard-ads/godfathers-pizza-602155dc
Delta Arkansas News: https://www.darnews.com/posterboard-ads/donut-house-bd68271e
```

---

## New Patterns Added

### Advertising & Promotional

| Pattern | Purpose | Examples |
|---------|---------|----------|
| `/posterboard-ads/` | Digital bulletin board ads | McDonald's, Donut House, Jimmy Clean |
| `/classifieds/` | Classified ad sections | Jobs, cars, real estate listings |
| `/marketplace/` | Marketplace/buy/sell pages | Facebook-style marketplaces |
| `/deals/` | Deal/coupon pages | Special offers, sales |
| `/coupons/` | Coupon pages | Printable/digital coupons |
| `/promotions/` | Promotional content | Contests, giveaways |
| `/sponsored/` | Sponsored content | Native advertising |

### Context

These patterns join existing filters for:
- Galleries (`/photo-gallery/`, `/video-gallery/`)
- Categories (`/category/`, `/tag/`, `/section/`)
- Static pages (`/about`, `/contact`, `/privacy/`)
- Technical pages (`.pdf`, `.xml`, `/api/`)

---

## Deployment

### Current Status

✅ **Changes committed** to feature branch  
⏳ **Not yet deployed** to production  
📋 **Will take effect** on next pipeline run

### When Changes Take Effect

1. **New discoveries**: Immediately upon deployment
   - Ad URLs will not be discovered
   - Will not enter the database

2. **Existing URLs**: No automatic cleanup
   - Old posterboard-ads URLs remain in database
   - Will not be re-discovered or updated
   - Can be manually marked if needed

### Testing in Production

After deployment, monitor discovery logs:

```bash
# Check that posterboard-ads URLs are being filtered
kubectl logs -n production -l app=mizzou-processor --tail=1000 | \
  grep -i "posterboard-ads"

# Should see messages like:
# "Filtered non-article by URL pattern: https://www.dddnews.com/posterboard-ads/..."
```

---

## Manual Cleanup (Optional)

If you want to mark existing posterboard-ads URLs as non-articles:

### Option 1: Mark as "not_article" status

```sql
UPDATE links
SET status = 'not_article'
WHERE url LIKE '%/posterboard-ads/%'
   OR url LIKE '%/classifieds/%'
   OR url LIKE '%/marketplace/%';
```

### Option 2: Delete from database

```sql
-- Backup first!
SELECT COUNT(*) FROM links WHERE url LIKE '%/posterboard-ads/%';

-- Then delete
DELETE FROM links
WHERE url LIKE '%/posterboard-ads/%'
   OR url LIKE '%/classifieds/%'
   OR url LIKE '%/marketplace/%';
```

**Note**: Manual cleanup is **optional**. The filters prevent new discoveries, and existing entries won't cause issues.

---

## Future Considerations

### Additional Patterns to Consider

If more advertising/promotional URL patterns emerge:

- `/e-edition/` - Digital newspaper editions (may include ads)
- `/circular/` - Weekly circulars/flyers
- `/bulletin-board/` - Community bulletin boards
- `/announcements/` - Business announcements
- `/events/` - Event listings (borderline - may include news events)

### Site-Specific Filtering

Some sites may use different URL patterns for ads:
- Monitor discovery logs for new patterns
- Add site-specific rules in crawler configuration
- Update `NON_ARTICLE_PATTERNS` as needed

---

## Related Files

### Modified
- `src/utils/url_classifier.py` - Main URL pattern filters
- `src/crawler/__init__.py` - Crawler link discovery filters

### Related (Not Modified)
- `src/services/url_verification.py` - Uses url_classifier
- `src/crawler/discovery.py` - Calls crawler filters
- `reports/*.csv` - Historical data showing posterboard-ads URLs

---

## Monitoring

### Success Metrics

After deployment, track:

1. **Discovery efficiency**: Fewer non-article URLs entering pipeline
2. **Processing time**: Reduced time spent on ad pages
3. **Classification accuracy**: Fewer misclassified ads as "obituary" or "civic information"

### Log Messages to Watch

```
# Good - URLs being filtered as expected
"Filtered non-article by URL pattern: .../posterboard-ads/..."

# Bad - If posterboard-ads URLs still getting through
"Discovered URL: .../posterboard-ads/..."
```

---

## Questions & Answers

**Q: Will this affect existing articles?**  
A: No. The filters only match specific advertising URL patterns. Real news articles are not affected.

**Q: What if a news site uses `/promotions/` for news about promotions?**  
A: Unlikely, but if it happens, add site-specific include rules to override the global filter.

**Q: Should we delete existing posterboard-ads URLs?**  
A: Optional. They'll no longer be discovered or updated, so they'll naturally age out of the system.

**Q: Can we add more patterns later?**  
A: Yes. Simply add to `NON_ARTICLE_PATTERNS` in `src/utils/url_classifier.py` and redeploy.

---

## Summary

✅ **Problem**: Advertising pages (posterboard-ads, classifieds) being treated as news articles  
✅ **Solution**: Added URL pattern filters to exclude advertising/promotional content  
✅ **Testing**: Verified filters work correctly  
✅ **Impact**: Cleaner discovery, fewer false positives  
✅ **Deployment**: Changes ready for next pipeline run

**Next steps**: Deploy to production and monitor discovery logs.
