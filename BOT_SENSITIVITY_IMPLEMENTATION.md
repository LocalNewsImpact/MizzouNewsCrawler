# Bot Sensitivity System Implementation

## Overview

Implement a bot sensitivity rating system (1-10 scale) for publishers to enable adaptive crawling behavior based on:
1. Pre-configured sensitivity levels for known bot-sensitive sites
2. Dynamic adjustment based on bot detection encounters (403, CAPTCHA, timeouts)
3. Automatic calibration of rate limiting, pauses, and backoff timings

## Database Schema Changes

### Add to `sources` table

```sql
-- Bot sensitivity rating (1-10 scale)
-- 1 = Very permissive (low sensitivity, fast crawling)
-- 5 = Moderate (balanced approach)
-- 10 = Extremely sensitive (aggressive bot detection, slow crawling)
ALTER TABLE sources ADD COLUMN bot_sensitivity INTEGER DEFAULT 5 CHECK (bot_sensitivity BETWEEN 1 AND 10);

-- Track when sensitivity was last updated
ALTER TABLE sources ADD COLUMN bot_sensitivity_updated_at TIMESTAMP NULL;

-- Track number of bot detection encounters
ALTER TABLE sources ADD COLUMN bot_encounters INTEGER DEFAULT 0;

-- Track last bot detection event
ALTER TABLE sources ADD COLUMN last_bot_detection_at TIMESTAMP NULL;

-- Additional metadata for bot detection patterns
ALTER TABLE sources ADD COLUMN bot_detection_metadata JSONB;
```

### Bot Detection Telemetry Table (Optional - for detailed tracking)

```sql
CREATE TABLE bot_detection_events (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    source_id VARCHAR NOT NULL REFERENCES sources(id),
    host VARCHAR NOT NULL,
    url VARCHAR NOT NULL,
    event_type VARCHAR NOT NULL,  -- '403_forbidden', 'captcha', 'rate_limit', 'timeout'
    http_status_code INTEGER,
    detection_method VARCHAR,  -- 'http_status', 'response_body', 'headers'
    response_indicators JSONB,  -- Detection signals found
    previous_sensitivity INTEGER,
    new_sensitivity INTEGER,
    adjustment_reason TEXT,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_bot_events_source ON bot_detection_events(source_id, detected_at DESC);
CREATE INDEX idx_bot_events_host ON bot_detection_events(host, detected_at DESC);
CREATE INDEX idx_bot_events_type ON bot_detection_events(event_type);
```

## Sensitivity Level Mappings

### Rate Limiting Parameters by Sensitivity

```python
BOT_SENSITIVITY_CONFIG = {
    1: {  # Very permissive
        "inter_request_min": 0.5,
        "inter_request_max": 1.5,
        "batch_sleep": 5.0,
        "captcha_backoff_base": 300,  # 5 minutes
        "captcha_backoff_max": 1800,  # 30 minutes
        "max_backoff": 120,
        "request_timeout": 10,
    },
    2: {  # Low sensitivity
        "inter_request_min": 1.0,
        "inter_request_max": 3.0,
        "batch_sleep": 10.0,
        "captcha_backoff_base": 450,
        "captcha_backoff_max": 2400,
        "max_backoff": 180,
        "request_timeout": 15,
    },
    3: {  # Below moderate
        "inter_request_min": 2.0,
        "inter_request_max": 5.0,
        "batch_sleep": 20.0,
        "captcha_backoff_base": 600,
        "captcha_backoff_max": 3600,
        "max_backoff": 240,
        "request_timeout": 20,
    },
    4: {  # Slightly cautious
        "inter_request_min": 3.0,
        "inter_request_max": 8.0,
        "batch_sleep": 30.0,
        "captcha_backoff_base": 900,
        "captcha_backoff_max": 4200,
        "max_backoff": 300,
        "request_timeout": 20,
    },
    5: {  # Moderate (current default)
        "inter_request_min": 5.0,
        "inter_request_max": 12.0,
        "batch_sleep": 60.0,
        "captcha_backoff_base": 1200,
        "captcha_backoff_max": 5400,
        "max_backoff": 300,
        "request_timeout": 20,
    },
    6: {  # Cautious
        "inter_request_min": 8.0,
        "inter_request_max": 18.0,
        "batch_sleep": 90.0,
        "captcha_backoff_base": 1800,
        "captcha_backoff_max": 7200,
        "max_backoff": 600,
        "request_timeout": 25,
    },
    7: {  # Very cautious
        "inter_request_min": 12.0,
        "inter_request_max": 25.0,
        "batch_sleep": 120.0,
        "captcha_backoff_base": 2400,
        "captcha_backoff_max": 9000,
        "max_backoff": 900,
        "request_timeout": 30,
    },
    8: {  # Highly sensitive
        "inter_request_min": 20.0,
        "inter_request_max": 35.0,
        "batch_sleep": 180.0,
        "captcha_backoff_base": 3600,
        "captcha_backoff_max": 10800,
        "max_backoff": 1200,
        "request_timeout": 30,
    },
    9: {  # Extremely sensitive
        "inter_request_min": 30.0,
        "inter_request_max": 50.0,
        "batch_sleep": 300.0,  # 5 minutes
        "captcha_backoff_base": 5400,
        "captcha_backoff_max": 14400,
        "max_backoff": 1800,
        "request_timeout": 30,
    },
    10: {  # Maximum caution - extremely aggressive bot detection
        "inter_request_min": 45.0,
        "inter_request_max": 90.0,
        "batch_sleep": 600.0,  # 10 minutes
        "captcha_backoff_base": 7200,
        "captcha_backoff_max": 21600,
        "max_backoff": 3600,
        "request_timeout": 30,
    },
}
```

### Dynamic Sensitivity Adjustment Rules

```python
SENSITIVITY_ADJUSTMENT_RULES = {
    # Event type -> (sensitivity_increase, max_sensitivity, base_cooldown_hours)
    # Base cooldown is for low sensitivity (1-4), scales exponentially for higher
    "403_forbidden": (2, 10, 1.0),  # +2 sensitivity, max 10, 1hr base cooldown
    "captcha_detected": (3, 10, 2.0),  # +3 sensitivity, max 10, 2hr base cooldown
    "rate_limit_429": (1, 8, 0.5),  # +1 sensitivity, max 8, 30min base cooldown
    "connection_timeout": (1, 7, 0.5),  # +1 sensitivity, max 7, 30min base cooldown
    "multiple_failures": (2, 9, 1.5),  # +2 sensitivity, max 9, 1.5hr base cooldown
}

# Adaptive cooldown multipliers by sensitivity level:
# Sensitivity 1-4: 1x base (30min - 2hr)
# Sensitivity 5-6: 2x base (1hr - 4hr)
# Sensitivity 7-8: 4x base (2hr - 8hr)
# Sensitivity 9-10: 8x base (4hr - 16hr)
# This prevents rapid adjustments at high sensitivity while staying responsive at low

# Decay rules (gradually reduce sensitivity if no issues)
SENSITIVITY_DECAY = {
    "success_threshold": 100,  # Successful requests before considering decay
    "decay_amount": 1,  # Reduce by 1 level
    "min_sensitivity": 3,  # Don't go below this
    "days_without_incident": 7,  # Required days without bot detection
}
```

## Pre-configured Known Sensitive Sites

```python
KNOWN_SENSITIVE_PUBLISHERS = {
    # Configure publishers with known aggressive bot detection
    # Add entries as you discover bot-sensitive sites:
    # "example-site.com": 10,  # Extremely sensitive - aggressive bot detection
    # "another-site.com": 7,   # Very cautious - moderate bot detection
    # Most sites will use default sensitivity (5) and auto-adjust
}
```

## Implementation Components

### 1. Database Migration

**File:** `alembic/versions/YYYYMMDD_add_bot_sensitivity.py`

### 2. Model Update

**File:** `src/models/__init__.py`
- Add `bot_sensitivity`, `bot_sensitivity_updated_at`, `bot_encounters`, etc. to `Source` model

### 3. Bot Sensitivity Manager

**File:** `src/utils/bot_sensitivity_manager.py`
- Load sensitivity config for host
- Adjust sensitivity on bot detection
- Apply rate limiting based on sensitivity
- Track encounters and decay

### 4. ContentExtractor Integration

**File:** `src/crawler/__init__.py`
- Query bot sensitivity before extraction
- Apply sensitivity-adjusted rate limits
- Detect bot responses and trigger sensitivity increase
- Report bot encounters

### 5. CLI Command for Management

**File:** `src/cli/commands/bot_sensitivity.py`
- List sources by sensitivity
- Manually set sensitivity for source
- View bot encounter history
- Export/import sensitivity profiles

### 6. API Endpoints

**File:** `backend/app/sources.py`
- `GET /sources/{id}/bot-sensitivity` - Get current sensitivity
- `PATCH /sources/{id}/bot-sensitivity` - Update sensitivity
- `GET /sources/{id}/bot-encounters` - View encounter history
- `POST /sources/{id}/bot-test` - Test bot detection (dry-run)

## Integration Flow

### Extraction Workflow

```python
# 1. Before extraction
source_info = get_source_for_url(url)
bot_sensitivity = source_info.bot_sensitivity or 5
config = get_rate_limit_config(bot_sensitivity)

# 2. Apply rate limits
apply_inter_request_delay(config["inter_request_min"], config["inter_request_max"])

# 3. Attempt extraction
try:
    content = extract_content(url)
    
    # Track successful extraction
    increment_success_counter(source_id)
    
    # Check for sensitivity decay opportunity
    check_sensitivity_decay(source_id)
    
except BotDetectionError as e:
    # 4. Handle bot detection
    log_bot_detection_event(
        source_id=source_id,
        url=url,
        event_type=e.type,  # '403', 'captcha', etc.
        indicators=e.indicators
    )
    
    # 5. Adjust sensitivity
    new_sensitivity = adjust_bot_sensitivity(
        source_id=source_id,
        current_sensitivity=bot_sensitivity,
        event_type=e.type
    )
    
    # 6. Apply adjusted backoff
    adjusted_backoff = calculate_backoff(new_sensitivity, e.type)
    domain_backoff_until[domain] = time.time() + adjusted_backoff
```

### Sensitivity Adjustment Logic

```python
def adjust_bot_sensitivity(source_id, current_sensitivity, event_type):
    """Increase bot sensitivity based on detection event."""
    
    # Get adjustment rules for event type
    increase, max_cap, cooldown_hours = SENSITIVITY_ADJUSTMENT_RULES[event_type]
    
    # Check cooldown
    last_adjustment = get_last_sensitivity_adjustment(source_id)
    if last_adjustment and (datetime.utcnow() - last_adjustment) < timedelta(hours=cooldown_hours):
        logger.info(f"Sensitivity adjustment in cooldown for {source_id}")
        return current_sensitivity
    
    # Calculate new sensitivity
    new_sensitivity = min(current_sensitivity + increase, max_cap)
    
    if new_sensitivity != current_sensitivity:
        update_source_sensitivity(
            source_id=source_id,
            new_sensitivity=new_sensitivity,
            reason=f"Bot detection: {event_type}",
            increment_encounters=True
        )
        
        logger.warning(
            f"Increased bot sensitivity for {source_id}: "
            f"{current_sensitivity} -> {new_sensitivity} (event: {event_type})"
        )
    
    return new_sensitivity
```

## Testing Strategy

### 1. Unit Tests
- Test sensitivity calculation
- Test rate limit config selection
- Test adjustment logic
- Test decay logic

### 2. Integration Tests
- Test sensitivity persistence
- Test extraction with different sensitivities
- Test bot detection triggering adjustment

### 3. End-to-End Tests
- Crawl known sensitive site (mocked responses)
- Verify rate limits applied correctly
- Verify sensitivity adjusts on simulated 403

## Deployment Strategy

1. **Phase 1: Schema Migration**
   - Add columns to `sources` table
   - Backfill known sensitive sites

2. **Phase 2: Read-Only Integration**
   - Implement sensitivity loading
   - Apply rate limits (no adjustment yet)
   - Monitor for issues

3. **Phase 3: Full Integration**
   - Enable bot detection
   - Enable sensitivity adjustment
   - Monitor adjustment behavior

4. **Phase 4: Optimization**
   - Fine-tune sensitivity thresholds
   - Adjust decay parameters
   - Add more known sensitive sites

## Monitoring & Alerting

### Metrics to Track
- Average sensitivity by source
- Bot detection events per day
- Sensitivity adjustments per day
- Success rate by sensitivity level
- Extraction time by sensitivity level

### Alerts
- Source reaches sensitivity 10 (max)
- Rapid sensitivity increases (>3 levels in 24h)
- High bot encounter rate (>10 per day for source)
- Sensitivity decay not working (stuck at high levels)

## Configuration Files

Create these files:
1. `src/config/bot_sensitivity.py` - Sensitivity configs
2. `alembic/versions/YYYYMMDD_add_bot_sensitivity.py` - Migration
3. `src/utils/bot_sensitivity_manager.py` - Core logic
4. `src/cli/commands/bot_sensitivity.py` - CLI tools
5. `scripts/backfill_known_sensitive_sites.py` - Initial data

## Migration Checklist

- [ ] Create Alembic migration
- [ ] Update Source model
- [ ] Implement BotSensitivityManager
- [ ] Integrate with ContentExtractor
- [ ] Add CLI commands
- [ ] Add API endpoints
- [ ] Write unit tests
- [ ] Write integration tests
- [ ] Backfill known sensitive sites
- [ ] Update documentation
- [ ] Deploy to staging
- [ ] Monitor for issues
- [ ] Deploy to production

## Benefits

1. **Adaptive Behavior**: Automatically adjusts to site protection changes
2. **Reduced Blocking**: Proactive caution prevents bans
3. **Faster Crawling**: Permissive sites get faster treatment
4. **Operational Intelligence**: Track which sites are bot-sensitive
5. **Historical Data**: Understand bot detection patterns over time
6. **Manual Override**: Operators can pre-configure known sensitive sites
