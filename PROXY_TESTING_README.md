# Proxy Testing Strategy

## Current Implementation (Squid-Only)

The proxy system has been completely migrated from Decodo to Squid-only implementation.

### Active Test Files

- **`tests/test_squid_only_proxy.py`** - Complete test coverage for Squid proxy system
  - Provider override validation
  - Unblock method integration
  - Error handling and fallbacks
  - Session proxy configuration
  - Environment variable support

### Test Coverage

✅ **Current Tests (10 tests)**
```bash
pytest tests/test_squid_only_proxy.py -v
# Should show 10 passing tests
```

Key test scenarios:
- `test_provider_override_with_squid_env` - Environment variable integration
- `test_unblock_method_uses_squid` - Method routing verification
- `test_error_handling_*` - Exception handling for various scenarios
- `test_session_proxy_configuration` - Requests session setup
- `test_semantic_labeling` - Provider labeling accuracy

## Deprecated Test Files

⚠️ **Deprecated (marked as skipped)**

- **`tests/test_unblock_proxy_extraction.py`** - Legacy Decodo proxy tests (1294 lines)
  - Marked with `pytest.mark.skip`
  - Contains deprecation warnings
  - Preserved for reference only

### Why Deprecated?

The original tests verified Decodo API integration including:
- X-SU-* header authentication
- Challenge page detection
- API POST fallback mechanisms
- Rotating proxy management
- Complex metadata extraction

All this functionality has been replaced with simple Squid proxy routing.

## Running Tests

### Current Proxy Tests Only
```bash
pytest tests/test_squid_only_proxy.py -v
```

### Skip Deprecated Tests (Default)
```bash
pytest tests/  # Automatically skips deprecated proxy tests
```

### Force Run Deprecated Tests (Not Recommended)
```bash
pytest tests/test_unblock_proxy_extraction.py --runxfail
# Will fail - tests expect old Decodo behavior
```

## Production Configuration

### Environment Variables
```bash
export SQUID_PROXY_URL="http://your-squid-server:3128"
# No authentication needed for current setup
```

### Proxy Provider
```python
from src.crawler.proxy_config import ProxyProvider
# ProxyProvider.SQUID = "squid"  # Added for semantic correctness
```

## Migration Notes

### What Changed
1. **Decodo → Squid**: All proxy routing now uses simple HTTP proxy
2. **Authentication**: No special headers or credentials needed
3. **Fallbacks**: Simplified error handling without complex retry logic
4. **Metadata**: Basic extraction info instead of detailed proxy metrics

### Test Impact
- **Removed**: 21 failing legacy tests (complex Decodo workflows)
- **Added**: 10 new tests (simple Squid verification)
- **Net Result**: Cleaner, faster test suite focused on current implementation

### Future Development

When adding proxy features:
1. ✅ Add tests to `test_squid_only_proxy.py`
2. ❌ Do NOT modify deprecated test files
3. ✅ Update this README with new test scenarios

The Squid-only approach prioritizes simplicity and maintainability over complex proxy management features.
