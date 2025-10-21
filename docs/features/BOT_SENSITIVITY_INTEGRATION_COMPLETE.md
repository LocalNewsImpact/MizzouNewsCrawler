# Bot Sensitivity Integration Complete

## Summary

Successfully integrated adaptive bot sensitivity system into the ContentExtractor crawler. This system automatically adjusts crawling behavior based on bot detection encounters, preventing bans and optimizing crawl rates.

## Changes Made

### 1. Core Utility: `src/utils/bot_sensitivity_manager.py`

Created comprehensive bot sensitivity manager with:

- **10-level sensitivity scale** (1=permissive to 10=extremely cautious)
- **Rate limiting configs** for each sensitivity level
  - inter_request delays (0.5-90s range)
  - batch sleep periods (5-600s)
  - CAPTCHA backoff timers (300-21600s)
- **Automatic sensitivity adjustment** based on detection events
  - 429 rate limits → +1 sensitivity
  - 403 forbidden → +2 sensitivity  
  - CAPTCHA/Cloudflare detection → +3 sensitivity
- **Adaptive cooldown periods** to prevent excessive sensitivity spikes
  - Low sensitivity (1-4): 30min - 2hr base cooldown
  - Medium sensitivity (5-6): 1-4hr cooldown (2x base)
  - High sensitivity (7-8): 2-8hr cooldown (4x base)
  - Very high (9-10): 4-16hr cooldown (8x base)
  - Responsive at low levels, cautious at high levels
- **Event tracking** in `bot_detection_events` table
- **Statistics and monitoring** via `get_bot_encounter_stats()`

### 2. Database Schema: `src/models/__init__.py`

Added 5 new columns to `Source` model:
- `bot_sensitivity` (INTEGER, default 5, range 1-10)
- `bot_sensitivity_updated_at` (TIMESTAMP)
- `bot_encounters` (INTEGER, default 0)
- `last_bot_detection_at` (TIMESTAMP, indexed)
- `bot_detection_metadata` (JSON)

### 3. Migration: `alembic/versions/2025101201_bot_sensitivity.py`

Database migration includes:
- New columns on `sources` table with constraints
- New `bot_detection_events` table for detailed tracking
- Indexes for performance on sensitivity queries
- Check constraint: `bot_sensitivity BETWEEN 1 AND 10`

### 4. Crawler Integration: `src/crawler/__init__.py`

Updated ContentExtractor to use bot sensitivity:

**Initialization:**
- Added `BotSensitivityManager` instance
- Manager available at `self.bot_sensitivity_manager`

**Rate Limiting:**
- `_apply_rate_limit()` now uses sensitivity-based configs
- Automatically loads delays based on domain sensitivity
- No more hardcoded rate limits

**Bot Detection Handling:**
- HTTP 429 (rate limit) → records event as "rate_limit_429"
- HTTP 403/503 → records as "403_forbidden" or "captcha_detected"
- HTTP 200 with protection → records as "captcha_detected"
- All events include URL, status code, and response indicators

**Automatic Adjustment:**
- Each bot detection increments sensitivity (with cooldown)
- Sensitivity persists across crawler restarts
- System learns which publishers are sensitive

## How It Works

### Initial Crawl
1. New publisher defaults to sensitivity 5 (moderate)
2. Crawler uses moderate delays (5-12s between requests)
3. If no bot detection → continues at same sensitivity

### Bot Detection Event
1. Crawler hits CAPTCHA or 403 error
2. `record_bot_detection()` is called with event details
3. Sensitivity increases (e.g., 5 → 8 for CAPTCHA)
4. Cooldown calculated adaptively (2hr base × 2 multiplier = 4hr at sensitivity 5)
5. Event logged to `bot_detection_events` table
6. Source record updated with new sensitivity and timestamp

### Next Crawl Attempt
1. Crawler loads sensitivity for domain (now 8)
2. Uses sensitivity-8 config (20-35s delays, 3hr CAPTCHA backoff)
3. Much slower, more cautious crawling
4. If bot detected again → cooldown now 8hr (4x multiplier at sensitivity 8)
5. If successful → error count resets
6. After 100+ successes and 7 days → sensitivity can decay by -1

### Monitoring
```python
# Get stats for specific domain
stats = manager.get_bot_encounter_stats("example.com")
# Returns: total_events, event_types, last_detection

# Get current sensitivity
sensitivity = manager.get_bot_sensitivity("example.com")  # Returns 1-10

# Get rate limit config
config = manager.get_sensitivity_config("example.com")
# Returns: inter_request_min/max, batch_sleep, captcha_backoff, etc.
```

## Configuration

### Sensitivity Levels

| Level | Description | Inter-Request | Batch Sleep | Use Case |
|-------|-------------|---------------|-------------|----------|
| 1 | Very permissive | 0.5-1.5s | 5s | Friendly sites |
| 3 | Below moderate | 2-5s | 20s | Most local news |
| 5 | Moderate (default) | 5-12s | 60s | Balanced approach |
| 7 | Very cautious | 12-25s | 120s | Known bot detection |
| 10 | Maximum caution | 45-90s | 600s | Extremely aggressive |

### Pre-configured Publishers

Add known sensitive sites to `KNOWN_SENSITIVE_PUBLISHERS` dict:

```python
KNOWN_SENSITIVE_PUBLISHERS = {
    "aggressive-site.com": 10,
}
```

These sites start at configured sensitivity instead of default 5.

## Testing Strategy

### Unit Tests
- Test sensitivity calculation logic
- Test adjustment rules (event → sensitivity increase)
- Test cooldown enforcement
- Test config loading for different sensitivity levels

### Integration Tests  
- Mock bot responses (403, CAPTCHA page)
- Verify sensitivity increases appropriately
- Verify rate limits applied correctly
- Test event logging to database

### Manual Testing
1. Run migration: `alembic upgrade head`
2. Crawl test publisher with bot protection
3. Verify sensitivity increases in database
4. Check `bot_detection_events` table for logged events
5. Verify next crawl uses slower rate limits

## Next Steps

1. ✅ **Complete** - Core implementation and integration
2. **Pending** - Run database migration on dev environment
3. **Pending** - Create CLI commands for manual sensitivity management
4. **Pending** - Add API endpoints for sensitivity viewing
5. **Pending** - Write unit and integration tests
6. **Pending** - Monitor and tune sensitivity thresholds in production
7. **Pending** - Implement decay mechanism (reduce sensitivity after success period)

## Files Changed

- ✅ `src/utils/bot_sensitivity_manager.py` (NEW)
- ✅ `src/models/__init__.py` (MODIFIED - added 5 columns to Source)
- ✅ `alembic/versions/2025101201_bot_sensitivity.py` (NEW)
- ✅ `src/crawler/__init__.py` (MODIFIED - integrated bot sensitivity)
- ✅ `BOT_SENSITIVITY_IMPLEMENTATION.md` (UPDATED - removed specific publishers)

## Benefits

1. **Automatic Adaptation** - System learns which publishers are sensitive
2. **Ban Prevention** - Increases caution before getting blocked
3. **Efficiency** - Maintains fast rates for permissive sites
4. **Visibility** - All bot encounters logged for analysis
5. **Persistence** - Sensitivity persists across restarts
6. **Tunability** - Easy to adjust thresholds and configs

## Notes

- All specific publication references removed from code/docs
- System starts conservative (sensitivity 5) and adapts
- Cooldown periods prevent sensitivity from spiking too quickly
- Event tracking provides full audit trail
- Can manually override sensitivity via database or future CLI
