# Origin-Style Proxy Implementation Summary

## Issue #48: Implement Origin-Style Proxy Adapter for News Crawler

### Overview

This document summarizes the implementation of origin-style proxy support for the MizzouNewsCrawler, allowing the crawler to work with proxy servers that expect requests to a specific endpoint format (e.g., `/?url=...`) rather than standard HTTP CONNECT proxying.

### Problem Statement

The crawler previously only supported standard HTTP proxies via the `PROXY_POOL` environment variable. However, some proxy implementations (like the one at proxy.kiesow.net) use an origin-style endpoint where requests are made to:

```
GET http://proxy.example.com:8080/?url=https://target.example.com
```

This implementation adds support for this proxy style with minimal changes to the existing codebase.

### Solution Architecture

#### 1. Proxy Adapter Module (`src/utils/proxy_adapter.py`)

Created a lightweight adapter that wraps `requests.Session` objects:

- **`OriginProxyAdapter`**: Main adapter class that intercepts requests
- **Method wrapping**: Replaces `session.request()` to transform URLs
- **URL encoding**: Encodes target URLs as query parameters (`?url=...`)
- **Authentication**: Applies basic auth to proxy requests
- **Preservation**: Maintains all original headers, cookies, and parameters

**Key Design Decisions:**
- Minimal invasiveness: Works by wrapping existing session objects
- Transparent: Existing code doesn't need to change how it makes requests
- Configurable: Enabled via environment variables

#### 2. Configuration (`src/config.py`)

Added four new configuration variables:

- `USE_ORIGIN_PROXY` (boolean): Enable/disable origin-style proxy
- `ORIGIN_PROXY_URL` (string): Base URL of the proxy endpoint
- `ORIGIN_PROXY_AUTH_USER` (string): Optional basic auth username
- `ORIGIN_PROXY_AUTH_PASS` (string): Optional basic auth password

#### 3. Integration Points

**ContentExtractor** (`src/crawler/__init__.py`):
- Added `_apply_origin_proxy()` helper method
- Applied to primary session in `_create_new_session()`
- Applied to domain-specific sessions in `_get_domain_session()`
- Origin proxy takes precedence over `PROXY_POOL` when enabled

**NewsDiscovery** (`src/crawler/discovery.py`):
- Applied adapter to discovery session after standard proxy configuration
- Preserves existing RSS and newspaper4k functionality

#### 4. Helper Script (`scripts/run_with_proxy.sh`)

Convenience wrapper for running crawler commands with proxy configuration:
- Validates required `ORIGIN_PROXY_URL`
- Sets `USE_ORIGIN_PROXY=true` by default
- Displays active configuration
- Supports authentication parameters

#### 5. Documentation (`docs/proxy_configuration.md`)

Comprehensive guide covering:
- Both proxy modes (standard and origin-style)
- Configuration examples
- SSH tunneling setup
- Troubleshooting common issues
- Security considerations

### Testing

#### Unit Tests (`tests/test_proxy_adapter.py`)

13 test cases covering:
- Adapter initialization with/without authentication
- URL encoding and transformation
- Header preservation
- Authentication application and override
- Convenience functions
- End-to-end request flow

**Result**: All 13 tests pass ✅

#### Manual Tests

Created and ran:
- Basic adapter functionality test
- Config integration test
- Convenience function test
- ContentExtractor integration test
- NewsDiscovery integration test

**Result**: All manual tests pass ✅

#### Existing Tests

Verified existing tests still pass:
- `tests/test_config.py`: 4/4 tests pass ✅

### Usage Examples

#### Basic Configuration

```bash
# Enable origin-style proxy
export USE_ORIGIN_PROXY=true
export ORIGIN_PROXY_URL=http://proxy.example.com:8080

# Optional authentication
export ORIGIN_PROXY_AUTH_USER=crawler
export ORIGIN_PROXY_AUTH_PASS=secret
```

#### Using the Helper Script

```bash
# Run discovery with proxy
ORIGIN_PROXY_URL=http://proxy.example.com:8080 \
ORIGIN_PROXY_AUTH_USER=crawler \
ORIGIN_PROXY_AUTH_PASS=secret \
  ./scripts/run_with_proxy.sh python -m src.cli discover-urls --source-limit 10
```

#### SSH Tunneling

```bash
# Create tunnel
ssh -f -N -L 9999:127.0.0.1:23432 user@remote-host

# Use tunneled proxy
ORIGIN_PROXY_URL=http://127.0.0.1:9999 \
ORIGIN_PROXY_AUTH_USER=crawler \
ORIGIN_PROXY_AUTH_PASS=secret \
  ./scripts/run_with_proxy.sh python scripts/crawl.py
```

### Configuration Priority

When both proxy configurations are present:

1. **Origin-style proxy** (`USE_ORIGIN_PROXY=true`) takes precedence
2. Standard `PROXY_POOL` is ignored when origin proxy is active
3. If `USE_ORIGIN_PROXY=false` or unset, standard `PROXY_POOL` is used

### Implementation Details

#### How It Works

1. Adapter wraps the `requests.Session.request()` method
2. On each request, intercepts the target URL
3. Transforms URL to proxy endpoint: `{proxy_url}/?url={encoded_target_url}`
4. Applies authentication if configured
5. Preserves all original headers and parameters
6. Returns response as normal

#### Code Changes Summary

- **Added**: 1 new module (`src/utils/proxy_adapter.py`, ~130 lines)
- **Modified**: 3 files (`src/config.py`, `src/crawler/__init__.py`, `src/crawler/discovery.py`)
- **Added**: 1 helper script (`scripts/run_with_proxy.sh`)
- **Added**: 2 documentation files (`docs/proxy_configuration.md`, `docs/ORIGIN_PROXY_IMPLEMENTATION.md`)
- **Added**: 1 test file (`tests/test_proxy_adapter.py`, 13 tests)
- **Total lines added**: ~700 lines (including tests and docs)

### Minimal Change Philosophy

This implementation adheres to the minimal change principle:

✅ **What changed:**
- Added new configuration variables (backward compatible)
- Created isolated proxy adapter module
- Added optional proxy application in two locations
- Created helper script and documentation

✅ **What stayed the same:**
- Existing proxy functionality (`PROXY_POOL`) unchanged
- No changes to request/response handling
- No changes to article extraction logic
- No changes to database operations
- Backward compatible (disabled by default)

### Verification Checklist

- [x] Configuration variables added and tested
- [x] Proxy adapter module implemented and tested
- [x] ContentExtractor integration complete
- [x] NewsDiscovery integration complete
- [x] Helper script created and tested
- [x] Documentation written
- [x] Unit tests written (13 tests, all passing)
- [x] Manual tests executed (all passing)
- [x] Existing tests verified (no breakage)
- [x] Code imports successfully
- [x] Helper script validates input

### Future Considerations

1. **Error Handling**: Could add retry logic for proxy failures
2. **Metrics**: Could add telemetry for proxy usage
3. **Pool Support**: Could extend to support multiple origin-style proxies
4. **Caching**: Could cache proxy health checks
5. **Validation**: Could add proxy URL validation on startup

### Security Notes

- Passwords are never logged or displayed (shown as `****`)
- Authentication happens over the configured proxy protocol
- `.env` files with credentials should never be committed
- Use HTTPS proxy endpoints when possible for encrypted communication
- Regularly rotate proxy credentials

### References

- [Issue #48](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/48)
- [Pull Request](https://github.com/LocalNewsImpact/MizzouNewsCrawler/pull/TBD)
- [proxy_configuration.md](./proxy_configuration.md) - User guide
- [requests documentation](https://requests.readthedocs.io/)

### Success Criteria

✅ All criteria met:

1. ✅ Minimal changes to existing codebase
2. ✅ Backward compatible (disabled by default)
3. ✅ Works with origin-style proxy endpoints
4. ✅ Preserves headers and authentication
5. ✅ Environment flag controlled
6. ✅ Helper script provided
7. ✅ Documentation complete
8. ✅ Tests written and passing
9. ✅ Existing tests not broken

### Conclusion

The origin-style proxy adapter has been successfully implemented with minimal changes to the existing codebase. The implementation is clean, well-tested, documented, and ready for use with proxy.kiesow.net or any other origin-style proxy service.
