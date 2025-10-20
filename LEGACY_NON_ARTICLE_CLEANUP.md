# Legacy Non-Article URL Cleanup

**Date**: October 19, 2025  
**Issue**: https://www.kfvs12.com/video-gallery/news/ got past StoryFilter

## Root Cause

The URL classifier (`src/utils/url_classifier.py`) was added on **October 10, 2025** (commit `0f9bbf1`).

This video-gallery URL was discovered on **September 19, 2025** - 3 weeks **before** the URL classifier existed.

## Current Behavior

✅ **URL classifier is working correctly NOW**
- Pattern `/video-gallery/` is in `NON_ARTICLE_PATTERNS`
- `is_likely_article_url()` correctly returns `False` for gallery URLs
- New gallery URLs are being filtered during discovery

## Legacy Data Cleanup

Found **8 legacy gallery URLs** in the database that were added before the classifier:

```sql
SELECT id, url, status FROM candidate_links
WHERE status IN ('article', 'extracted', 'pending')
AND url LIKE '%/video-gallery/%' OR url LIKE '%/photo-gallery/%' OR url LIKE '%/gallery/%'
```

### Cleanup Action Taken

Marked all 8 URLs as `filtered` with error message:
```
Non-article URL pattern (gallery/video page)
```

### Affected URLs
- `https://www.kfvs12.com/video-gallery/news/` (was: article)
- `https://www.kfvs12.com/video-gallery/news` (was: article)
- `https://www.kfvs12.com/video-gallery/news/afternoon-originals/` (was: extracted)
- `https://www.kctv5.com/video-gallery/news/cinco-con-carolina/` (was: extracted)
- `https://www.emissourian.com/gallery/sports/softball-washington-at-pacific/collection_...` (was: extracted)
- And 3 more

## Prevention

✅ **No action needed** - the URL classifier is already preventing new non-article URLs from being added.

## Pattern Coverage

Current NON_ARTICLE_PATTERNS includes:
- `/video-gallery/`
- `/photo-gallery/`
- `/photos/`
- `/videos/`
- `/galleries/`
- `/gallery/`
- `/slideshow`
- `/category/`
- `/tag/`
- `/topics?/`
- And more...

## Verification

```python
from src.utils.url_classifier import is_likely_article_url
is_likely_article_url('https://www.kfvs12.com/video-gallery/news/')
# Returns: False ✅
```
