# Bot Sensitivity Cooldown Adjustment Summary

## Changes Made

Updated the bot sensitivity system to use **adaptive cooldowns** that scale based on current sensitivity level, making the system much more responsive at low sensitivity levels while still being cautious at high levels.

## Previous Behavior (Too Aggressive)

- HTTP 429: 12 hour cooldown
- HTTP 403: 24 hour cooldown  
- CAPTCHA: 48 hour cooldown

**Problem:** These long cooldowns prevented quick adjustments for low-sensitivity publishers, making the system too slow to respond to changing conditions.

## New Behavior (Adaptive)

### Base Cooldowns (for sensitivity 1-4)

- HTTP 429 rate limit: **30 minutes** base
- HTTP 403 forbidden: **1 hour** base
- CAPTCHA/Cloudflare: **2 hours** base
- Connection timeout: **30 minutes** base
- Multiple failures: **1.5 hours** base

### Cooldown Multipliers by Sensitivity

The base cooldown is multiplied based on current sensitivity:

| Sensitivity Level | Multiplier | Example (CAPTCHA 2hr base) |
|-------------------|------------|----------------------------|
| 1-4 (Low)         | 1x         | 2 hours                    |
| 5-6 (Medium)      | 2x         | 4 hours                    |
| 7-8 (High)        | 4x         | 8 hours                    |
| 9-10 (Very High)  | 8x         | 16 hours                   |

## Benefits

1. **Responsive at Low Sensitivity**: Publishers at sensitivity 1-4 can be adjusted within 30min-2hr, allowing quick adaptation

2. **Cautious at High Sensitivity**: Publishers at sensitivity 9-10 have 4-16hr cooldowns, preventing rapid sensitivity spikes for already-problematic sites

3. **Gradual Scaling**: The exponential multiplier (1x→2x→4x→8x) creates smooth progression as sensitivity increases

4. **Event-Specific**: Different event types have different base cooldowns:
   - Quick events (timeouts, 429s): 30min base
   - Moderate events (403s): 1hr base  
   - Severe events (CAPTCHA): 2hr base

## Example Scenarios

### Scenario 1: New Publisher (Sensitivity 5)

1. First CAPTCHA detected → sensitivity 5 → 8
2. Cooldown: 2hr × 2 = **4 hours**
3. If another CAPTCHA in 4 hours → no adjustment (in cooldown)
4. After 4 hours, another CAPTCHA → sensitivity 8 → 10
5. Cooldown: 2hr × 4 = **8 hours** (sensitivity now 8+)

### Scenario 2: Permissive Publisher (Sensitivity 2)

1. Occasional 403 error → sensitivity 2 → 4
2. Cooldown: 1hr × 1 = **1 hour**
3. Quick recovery if it was a transient issue
4. System stays responsive for low-sensitivity sites

### Scenario 3: Known Problem Publisher (Sensitivity 9)

1. CAPTCHA detected → sensitivity 9 → 10 (maxed)
2. Cooldown: 2hr × 8 = **16 hours**
3. Long cooldown prevents constant adjustment
4. Already at maximum caution level

## Code Changes

### `src/utils/bot_sensitivity_manager.py`

**Updated `SENSITIVITY_ADJUSTMENT_RULES`:**
```python
# Event type -> (sensitivity_increase, max_sensitivity, base_cooldown_hours)
SENSITIVITY_ADJUSTMENT_RULES = {
    "403_forbidden": (2, 10, 1.0),      # 1hr base
    "captcha_detected": (3, 10, 2.0),   # 2hr base
    "rate_limit_429": (1, 8, 0.5),      # 30min base
    "connection_timeout": (1, 7, 0.5),  # 30min base
    "multiple_failures": (2, 9, 1.5),   # 1.5hr base
}
```

**Updated `_calculate_adjusted_sensitivity()` method:**
- Calculates adaptive cooldown based on current sensitivity
- Uses exponential multiplier (1x, 2x, 4x, 8x)
- Logs cooldown with current sensitivity context

**Updated `_is_in_cooldown()` signature:**
- Changed parameter type from `int` to `float` to support fractional hours

## Documentation Updates

- `BOT_SENSITIVITY_IMPLEMENTATION.md` - Updated adjustment rules section
- `BOT_SENSITIVITY_INTEGRATION_COMPLETE.md` - Added adaptive cooldown details
- Removed all specific publication references

## Testing Recommendations

1. **Low Sensitivity Test**: Set publisher to sensitivity 2, trigger 403, verify 1hr cooldown
2. **High Sensitivity Test**: Set publisher to sensitivity 8, trigger CAPTCHA, verify 8hr cooldown
3. **Progression Test**: Track sensitivity from 3→5→7→9, verify cooldown increases: 2hr→4hr→8hr→16hr
4. **Cooldown Enforcement**: Trigger multiple events within cooldown window, verify only first adjusts

## Migration Impact

No database migration changes needed - this is purely a logic change in the bot sensitivity manager. Existing database schema supports this behavior.
