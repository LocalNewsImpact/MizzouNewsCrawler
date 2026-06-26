# AMP PerimeterX Bypass Implementation

## Summary
Implemented automatic AMP URL detection and conversion to bypass PerimeterX bot protection on news sites. The system now:

1. **Detects PerimeterX protection** (403 status codes)
2. **Automatically tries AMP URLs** before falling back to Selenium
3. **Caches AMP support status** in the database for future optimization
4. **Tracks telemetry** for success/failure rates

## Implementation Details

### 1. Database Schema (`alembic/versions/b1c2d3e4f5a6_add_amp_supported_to_sources.py`)
- Added `amp_supported` BOOLEAN column to `sources` table
- Default value: `FALSE`
- Index: `ix_sources_amp_supported` for fast queries
- Tracks which domains support AMP pages

### 2. AMP Utility Methods (`src/crawler/__init__.py`)

#### `_convert_to_amp_url(url: str) -> List[str]`
Generates AMP URL variations for a given URL:
- `/amp/` suffix (most common pattern, e.g., `https://fox4kc.com/article/amp/`)
- `?amp=1` query parameter
- Google AMP Cache format (`https://domain-com.cdn.ampproject.org/...`)

#### `_validate_amp_page(html: str) -> bool`
Validates if HTML is a genuine AMP page by checking for:
- `<html amp>` or `<html ⚡>` tags
- `ampproject.org` references
- `amp-boilerplate` and `amp-custom` tags

#### `_test_amp_support(domain: str, sample_url: Optional[str]) -> bool`
Tests if a domain supports AMP:
- Tries all AMP URL patterns
- Validates response is genuine AMP
- Updates `sources` table with result
- Caches result in memory

#### `_mark_domain_amp_supported(domain: str, supported: bool)`
Updates database to record AMP support status

#### `_get_domain_amp_support(domain: str) -> Optional[bool]`
Checks if domain is known to support AMP:
- Returns `True` if known to support
- Returns `False` if known NOT to support
- Returns `None` if unknown (not tested yet)
- Uses in-memory cache for performance

### 3. Integration into `_extract_with_newspaper()`

#### Proactive AMP Fetching
When domain is **known** to support AMP (`amp_supported=True`):
1. Check database at start of extraction
2. If `amp_supported=True`, try AMP URLs **before** normal HTTP request
3. If successful, skip normal request entirely
4. Records telemetry as `amp_preemptive_success`

```python
# Check if domain is known to support AMP - try AMP first if so
amp_supported = self._get_domain_amp_support(domain)
if amp_supported is True:
    logger.info(f"🔄 Domain {domain} known to support AMP, trying AMP first")
    amp_urls = self._convert_to_amp_url(url)
    # Try each AMP URL pattern...
```

#### Reactive AMP Bypass (PerimeterX Detection)
When PerimeterX protection is detected (403 response):
1. Detect PerimeterX via `_detect_bot_protection_in_response()`
2. Try all AMP URL patterns
3. Validate AMP page structure
4. If successful:
   - Mark domain as `amp_supported=True` in database
   - Record `amp_bypass_success` telemetry
   - Use AMP HTML for extraction
   - Continue with normal parsing flow
5. If failed:
   - Mark domain as `amp_supported=False` in database
   - Record `amp_bypass_failure` telemetry
   - Fall back to Selenium

```python
# Try AMP bypass for PerimeterX before marking domain or falling back
if protection_type == "perimeterx":
    logger.info(f"🔄 Attempting AMP bypass for PerimeterX on {domain}")
    amp_urls = self._convert_to_amp_url(url)
    # Try each AMP URL...
    if amp_success:
        # Successfully bypassed with AMP, continue to parsing
        logger.info(f"✅ Successfully used AMP to bypass PerimeterX on {domain}")
    else:
        # AMP bypass failed, record and continue to fallback
        logger.warning(f"❌ AMP bypass failed for {domain}, trying Selenium")
        # Fall back to Selenium...
```

### 4. Telemetry Tracking

Three new event types tracked via `bot_sensitivity_manager`:

1. **`amp_preemptive_success`**: AMP used proactively for known-supported domain
2. **`amp_bypass_success`**: AMP successfully bypassed PerimeterX detection
3. **`amp_bypass_failure`**: AMP bypass attempted but failed

All events include:
- `host`: Domain name
- `url`: Full URL attempted
- `http_status_code`: Response status
- `response_indicators`: Additional context (protection type, AMP URL used)

## Extraction Flow

### Before (without AMP):
```
HTTP Request → 403 PerimeterX → Mark domain selenium_only → Raise exception → Selenium fallback
```

### After (with AMP):
```
Known AMP domain:
  AMP Request → 200 Success → Parse content (Selenium not needed)

Unknown domain with PerimeterX:
  HTTP Request → 403 PerimeterX → Try AMP URLs → 200 Success → Parse content (Selenium not needed)
  
Failed AMP:
  HTTP Request → 403 PerimeterX → Try AMP URLs → All fail → Selenium fallback
```

## Confirmed Working Sites

Based on testing, the following PerimeterX sites support AMP:
- ✅ **fox4kc.com** - `/amp/` suffix works
- ✅ **fourstateshomepage.com** - `/amp/` suffix works
- 🔄 **fox2now.com** - Not yet tested
- 🔄 **ozarksfirst.com** - Not yet tested

## Benefits

1. **Faster Extraction**: AMP pages are lighter than Selenium
2. **Cost Savings**: Reduces Selenium usage (expensive compute)
3. **Better Success Rate**: Bypasses PerimeterX without detection
4. **Automatic Learning**: Database tracks which domains support AMP
5. **Graceful Degradation**: Falls back to Selenium if AMP fails

## Testing

### Unit Tests

Comprehensive test suite located in `tests/`:
- **`test_amp_bypass.py`** - 23 unit tests for individual methods
- **`test_amp_integration.py`** - 8 integration tests for full extraction flow

Run all tests:
```bash
python -m pytest tests/test_amp_bypass.py tests/test_amp_integration.py -v
```

See [tests/AMP_TESTS_README.md](tests/AMP_TESTS_README.md) for detailed test documentation.

### Integration Test Script

Run the integration test to verify against real URLs:
```bash
python test_amp_integration.py
```

Expected output:
- fox4kc.com: ✅ Success with AMP
- fourstateshomepage.com: ✅ Success with AMP

## Next Steps

1. **Run Migration**: Apply database schema change
   ```bash
   cd /Users/kiesowd/VSCode/NewsCrawler/MizzouNewsCrawler-Scripts
   alembic upgrade head
   ```

2. **Test Production Sites**: Verify AMP bypass on all 4 PerimeterX sites
   - fox4kc.com
   - fox2now.com  
   - fourstateshomepage.com
   - ozarksfirst.com

3. **Monitor Telemetry**: Check `bot_sensitivity_manager` logs for:
   - `amp_bypass_success` rate
   - `amp_bypass_failure` rate
   - `amp_preemptive_success` usage

4. **Update Other Sites**: Consider adding AMP support detection for other bot-protected domains

## Files Modified

1. `alembic/versions/b1c2d3e4f5a6_add_amp_supported_to_sources.py` - New migration
2. `src/crawler/__init__.py` - Added 6 new methods + integration logic (~200 lines)
3. `test_amp_integration.py` - New test script

## Canonical URL Handling

**Important**: AMP pages contain `<link rel="canonical">` tags pointing to the original non-AMP URL. The extraction process should preserve this canonical URL in the database, not the AMP URL. This ensures:
- Deduplication works correctly
- URLs are user-friendly
- Content is properly attributed

The newspaper4k library should automatically extract canonical URLs from AMP pages.
