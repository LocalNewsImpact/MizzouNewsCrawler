# Telemetry Type Validation

**Date:** October 19, 2025  
**Issue:** Multiple telemetry SQL errors due to type mismatches

## Database Schema for extraction_telemetry_v2

| Column | DB Type | Python Type | Conversion Needed |
|--------|---------|-------------|-------------------|
| operation_id | varchar | str | ✅ No |
| article_id | varchar | str | ✅ No |
| url | varchar | str | ✅ No |
| publisher | varchar | str/None | ✅ No |
| host | varchar | str/None | ✅ No |
| start_time | timestamp | datetime | ✅ No |
| end_time | timestamp | datetime/None | ✅ No |
| total_duration_ms | double precision | float | ✅ No |
| http_status_code | integer | int/None | ✅ No |
| http_error_type | varchar | str/None | ✅ No |
| response_size_bytes | integer | int | ✅ No |
| response_time_ms | double precision | float | ✅ No |
| **proxy_used** | **integer** | **bool** | ⚠️ **int() required** |
| proxy_url | varchar | str/None | ✅ No |
| **proxy_authenticated** | **integer** | **bool** | ⚠️ **int() required** |
| proxy_status | integer | int/None | ✅ No (string in code, needs fix) |
| proxy_error | varchar | str/None | ✅ No |
| methods_attempted | text | list (JSON) | ✅ json.dumps() |
| successful_method | varchar | str/None | ✅ No |
| method_timings | text | dict (JSON) | ✅ json.dumps() |
| method_success | text | dict (JSON) | ✅ json.dumps() |
| method_errors | text | dict (JSON) | ✅ json.dumps() |
| field_extraction | text | dict (JSON) | ✅ json.dumps() |
| extracted_fields | text | dict (JSON) | ✅ json.dumps() |
| final_field_attribution | text | dict (JSON) | ✅ json.dumps() |
| alternative_extractions | text | dict (JSON) | ✅ json.dumps() |
| content_length | integer | int | ✅ No |
| is_success | boolean | bool | ✅ No (currently int(), acceptable) |
| error_message | text | str/None | ✅ No |
| error_type | varchar | str/None | ✅ No |

## Issues Found and Fixed

### 1. ✅ Extra Placeholder (commit: ddb6667)
- **Problem:** 31 placeholders but 30 values
- **Fix:** Removed extra `?` from VALUES clause

### 2. ✅ Boolean to Integer Conversion (commit: 5c23c5c)
- **Problem:** `proxy_used` and `proxy_authenticated` sent as Python bool
- **Error:** `invalid input syntax for type integer: "false"`
- **Fix:** Convert to int: `int(metrics.proxy_used) if metrics.proxy_used is not None else None`

### 3. ⚠️ Potential Issue: proxy_status Type Mismatch
- **DB Schema:** `proxy_status integer`
- **Python Code:** `self.proxy_status: str | None = None`  (line 68)
- **Comment in code:** `# success, failed, bypassed, disabled` (strings!)
- **Status:** ⚠️ **NEEDS INVESTIGATION** - Schema says integer but code treats as string

## Recommendations

### Immediate Fix Required
The `proxy_status` field has a type mismatch:
- Database expects: `integer`
- Code provides: `str` ("success", "failed", "bypassed", "disabled")

**Options:**
1. **Change DB schema** to `varchar` (recommended - more readable)
2. **Change code** to use integer status codes (0=disabled, 1=success, 2=failed, 3=bypassed)

### Testing Strategy
To catch these errors earlier:
1. Add type validation before SQL INSERT
2. Create a unit test that validates ExtractionMetrics types against schema
3. Add schema introspection to verify column order and types

### Safe Conversions Applied
```python
# Boolean to integer (for proxy fields)
int(metrics.proxy_used) if metrics.proxy_used is not None else None
int(metrics.proxy_authenticated) if metrics.proxy_authenticated is not None else None

# Boolean to int for is_success (PostgreSQL accepts both)
int(is_success)  # 0 or 1 for boolean column
```

## Next Steps
1. Investigate `proxy_status` field - likely never populated so hasn't caused errors yet
2. Consider adding runtime type validation
3. Add integration test that actually inserts telemetry record
