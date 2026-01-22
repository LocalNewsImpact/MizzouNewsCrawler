# AMP Bypass Unit Tests

## Overview

Comprehensive unit and integration tests for the AMP bypass functionality that automatically converts URLs to AMP format to bypass PerimeterX bot protection.

## Test Files

### `test_amp_bypass.py`
Unit tests for individual AMP methods:
- **TestAMPURLConversion**: Tests `_convert_to_amp_url()` method
  - Basic /amp/ suffix conversion
  - Query parameter handling (?amp=1)
  - Google AMP Cache format
  - Edge cases (trailing slashes, existing params)
  
- **TestAMPPageValidation**: Tests `_validate_amp_page()` method
  - Recognition of `<html amp>` tag
  - Recognition of `<html ⚡>` tag
  - Detection of ampproject.org references
  - Detection of amp-boilerplate and amp-custom
  - Rejection of non-AMP pages
  
- **TestAMPDatabaseOperations**: Tests database interaction methods
  - `_mark_domain_amp_supported()` with True/False
  - `_get_domain_amp_support()` with known/unknown domains
  - Caching behavior
  
- **TestAMPTestSupport**: Tests `_test_amp_support()` method
  - Successful AMP detection
  - Failed AMP detection (404, invalid AMP)
  - Database updates

### `test_amp_integration.py`
Integration tests for full extraction flow:
- **TestAMPBypassIntegration**:
  - Complete flow: 403 PerimeterX → Try AMP → Success
  - Preemptive AMP fetch for known domains
  - AMP bypass failure → Selenium fallback
  - Normal flow for non-PerimeterX sites
  
- **TestAMPURLPatterns**:
  - Real-world URL patterns (fox4kc.com, fourstateshomepage.com)
  - Complex URLs with parameters and fragments

## Running Tests

### Run all AMP tests:
```bash
cd /Users/kiesowd/VSCode/NewsCrawler/MizzouNewsCrawler-Scripts
python -m pytest tests/test_amp_bypass.py tests/test_amp_integration.py -v
```

### Run specific test class:
```bash
python -m pytest tests/test_amp_bypass.py::TestAMPURLConversion -v
```

### Run specific test:
```bash
python -m pytest tests/test_amp_bypass.py::TestAMPURLConversion::test_convert_to_amp_url_basic -v
```

### Run with output:
```bash
python -m pytest tests/test_amp_bypass.py -v -s
```

### Run with coverage:
```bash
python -m pytest tests/test_amp_bypass.py tests/test_amp_integration.py --cov=src.crawler --cov-report=html
```

## Test Coverage

### Methods Tested:
- ✅ `_convert_to_amp_url()` - 6 tests
- ✅ `_validate_amp_page()` - 8 tests
- ✅ `_mark_domain_amp_supported()` - 2 tests
- ✅ `_get_domain_amp_support()` - 4 tests
- ✅ `_test_amp_support()` - 3 tests
- ✅ Integration flow - 4 tests
- ✅ URL patterns - 4 tests

**Total: 31 unit/integration tests**

## Test Strategy

### Unit Tests (test_amp_bypass.py)
- Mock all external dependencies (database, HTTP requests)
- Test individual methods in isolation
- Verify correct behavior for success/failure cases
- Ensure proper error handling

### Integration Tests (test_amp_integration.py)
- Mock HTTP responses to simulate real scenarios
- Test complete extraction flow end-to-end
- Verify telemetry tracking
- Ensure proper fallback behavior

## Mocking Strategy

### Database Mocking
- `DatabaseManager` is mocked to avoid real DB connections
- Session and execute methods are mocked with expected responses
- Commit calls are verified

### HTTP Mocking
- `_get_domain_session()` returns mock session objects
- Mock responses simulate:
  - 403 PerimeterX blocks
  - 200 AMP success
  - 404 not found
  - Valid/invalid AMP HTML

### Telemetry Mocking
- `BotSensitivityManager` is mocked to verify event recording
- Event types verified: `amp_bypass_success`, `amp_bypass_failure`, `amp_preemptive_success`

## Expected Test Results

All tests should pass with this output pattern:

```
tests/test_amp_bypass.py::TestAMPURLConversion::test_convert_to_amp_url_basic PASSED
tests/test_amp_bypass.py::TestAMPURLConversion::test_convert_to_amp_url_with_trailing_slash PASSED
tests/test_amp_bypass.py::TestAMPURLConversion::test_convert_to_amp_url_query_param PASSED
...
tests/test_amp_integration.py::TestAMPBypassIntegration::test_full_amp_bypass_flow PASSED
tests/test_amp_integration.py::TestAMPBypassIntegration::test_preemptive_amp_for_known_domain PASSED
...

======================== 31 passed in 0.45s ========================
```

## Troubleshooting

### Import Errors
If you see import errors for `src.crawler`:
```bash
export PYTHONPATH="/Users/kiesowd/VSCode/NewsCrawler/MizzouNewsCrawler-Scripts:$PYTHONPATH"
```

### Mock Not Found Errors
Ensure all patches use the correct import path:
- Use `src.crawler.DatabaseManager` not just `DatabaseManager`
- Use `src.crawler.ContentExtractor` for methods

### Database Connection Errors
Tests should NOT connect to real database. If you see connection errors:
- Check that `@patch('src.crawler.DatabaseManager')` is present
- Verify mock is applied before test execution

## Adding New Tests

When adding new AMP-related functionality:

1. **Add unit tests** in `test_amp_bypass.py`:
   ```python
   def test_new_feature(self):
       extractor = ContentExtractor()
       result = extractor._new_method()
       assert result == expected_value
   ```

2. **Add integration tests** in `test_amp_integration.py`:
   ```python
   @patch('src.crawler.ContentExtractor._dependency')
   def test_new_integration(self, mock_dep):
       # Setup mocks
       # Execute flow
       # Verify behavior
   ```

3. **Update this README** with new test counts

## CI/CD Integration

To add these tests to CI pipeline:

```yaml
- name: Run AMP Bypass Tests
  run: |
    python -m pytest tests/test_amp_bypass.py tests/test_amp_integration.py -v --junitxml=test-results/amp-tests.xml
```

## Manual Testing

For manual verification beyond unit tests:

```bash
# Test real URLs
python test_amp_integration.py

# Test specific domain
python -c "
from src.crawler import ContentExtractor
ext = ContentExtractor()
result = ext._convert_to_amp_url('https://fox4kc.com/article/')
print(result)
"
```

## Notes

- Tests use realistic HTML samples that match actual PerimeterX and AMP pages
- Mock responses include proper status codes and headers
- Telemetry tracking is verified to ensure metrics are captured
- All tests are independent and can run in any order
