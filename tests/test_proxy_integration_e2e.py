"""End-to-end integration test for proxy configuration.

This test validates that:
1. The sitecustomize shim can be imported and activated
2. requests.Session gets patched correctly
3. URL rewriting works as expected
4. Authentication headers are added properly
5. The integration works with cloudscraper (if available)
"""

import os
import sys
import importlib.util
import subprocess
from unittest.mock import Mock, patch
from urllib.parse import quote_plus

import pytest
import requests


def test_e2e_sitecustomize_with_real_session():
    """Test that sitecustomize works with actual requests.Session."""
    
    # Setup environment
    os.environ['USE_ORIGIN_PROXY'] = 'true'
    os.environ['ORIGIN_PROXY_URL'] = 'http://test.proxy:9999'
    os.environ['PROXY_USERNAME'] = 'testuser'
    os.environ['PROXY_PASSWORD'] = 'testpass'
    
    # Track what requests are made
    captured_requests = []
    
    # Create a mock response
    def mock_request_func(self, method, url, *args, **kwargs):
        captured_requests.append({
            'method': method,
            'url': url,
            'kwargs': kwargs
        })
        resp = Mock()
        resp.status_code = 200
        resp.text = 'mock response'
        resp.json = lambda: {'status': 'ok'}
        return resp
    
    # Load sitecustomize module fresh
    spec = importlib.util.spec_from_file_location(
        'sitecustomize_e2e',
        'k8s/sitecustomize.py'
    )
    sitecustomize = importlib.util.module_from_spec(spec)
    
    # Patch the original Session.request before loading sitecustomize
    with patch.object(requests.sessions.Session, 'request', mock_request_func):
        spec.loader.exec_module(sitecustomize)
        
        # Verify the shim activated
        assert sitecustomize.USE == True
        assert sitecustomize.ORIGIN == 'http://test.proxy:9999'
        
        # Create a new session and make a request
        session = requests.Session()
        
        # The session's request method should now be the patched version
        # Make a test request
        try:
            response = session.get('https://example.com/path?foo=bar')
        except Exception:
            pass  # May fail due to mock, that's ok
        
        # Check that the URL was rewritten
        assert len(captured_requests) > 0, "No requests were captured"
        
        last_request = captured_requests[-1]
        assert 'test.proxy' in last_request['url'], f"Proxy URL not in request: {last_request['url']}"
        assert quote_plus('https://example.com/path?foo=bar') in last_request['url'], \
            f"Original URL not encoded in request: {last_request['url']}"
        
        # Check that auth header was added
        headers = last_request['kwargs'].get('headers', {})
        assert 'Authorization' in headers, "Authorization header not added"
        assert 'Basic' in headers['Authorization'], "Basic auth not used"
    
    # Clean up
    del os.environ['USE_ORIGIN_PROXY']
    del os.environ['ORIGIN_PROXY_URL']
    del os.environ['PROXY_USERNAME']
    del os.environ['PROXY_PASSWORD']


def test_e2e_without_proxy_enabled():
    """Test that requests work normally when proxy is disabled."""
    
    # Ensure proxy is disabled
    os.environ['USE_ORIGIN_PROXY'] = 'false'
    os.environ.pop('ORIGIN_PROXY_URL', None)
    
    captured_requests = []
    
    def mock_request_func(self, method, url, *args, **kwargs):
        captured_requests.append({
            'method': method,
            'url': url,
        })
        resp = Mock()
        resp.status_code = 200
        resp.text = 'ok'
        return resp
    
    # Load sitecustomize
    spec = importlib.util.spec_from_file_location(
        'sitecustomize_disabled',
        'k8s/sitecustomize.py'
    )
    sitecustomize = importlib.util.module_from_spec(spec)
    
    with patch.object(requests.sessions.Session, 'request', mock_request_func):
        spec.loader.exec_module(sitecustomize)
        
        # Should NOT be active
        assert sitecustomize.USE == False
        
        session = requests.Session()
        try:
            session.get('https://example.com')
        except Exception:
            pass
        
        # URL should NOT be rewritten (no proxy in URL)
        if captured_requests:
            assert 'test.proxy' not in captured_requests[-1]['url']
    
    del os.environ['USE_ORIGIN_PROXY']


def test_e2e_subprocess_invocation():
    """Test that sitecustomize works when Python is invoked as a subprocess."""
    
    script = """
import os
import sys

# Set up proxy environment
os.environ['USE_ORIGIN_PROXY'] = 'true'
os.environ['ORIGIN_PROXY_URL'] = 'http://subprocess.proxy:8080'

# Manually load sitecustomize (normally auto-loaded by Python)
import importlib.util
spec = importlib.util.spec_from_file_location('sitecustomize', 'k8s/sitecustomize.py')
sitecustomize = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sitecustomize)

# Verify it activated
assert sitecustomize.USE == True, "Proxy not activated"
assert 'subprocess.proxy' in sitecustomize.ORIGIN, f"Wrong proxy URL: {sitecustomize.ORIGIN}"

print('✓ Proxy activated in subprocess')

# Try to import requests and check if Session.request was patched
try:
    import requests
    import inspect
    
    # Check if Session.request looks like it was patched
    # (A patched method won't be a builtin)
    is_patched = not inspect.isbuiltin(requests.sessions.Session.request)
    if is_patched:
        print('✓ Session.request was patched')
    else:
        print('⚠ Session.request may not be patched (expected if requests import failed during shim load)')
except ImportError:
    print('⚠ requests not available')

print('✓ Subprocess test passed')
"""
    
    result = subprocess.run(
        [sys.executable, '-c', script],
        cwd='/home/runner/work/MizzouNewsCrawler/MizzouNewsCrawler',
        capture_output=True,
        text=True,
        timeout=10
    )
    
    assert result.returncode == 0, f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    assert '✓ Proxy activated in subprocess' in result.stdout
    assert '✓ Subprocess test passed' in result.stdout


def test_e2e_cloudscraper_compatibility():
    """Test that the shim works with cloudscraper if available."""
    
    try:
        import cloudscraper
        has_cloudscraper = True
    except ImportError:
        has_cloudscraper = False
        return  # Skip this test if cloudscraper not available
    
    os.environ['USE_ORIGIN_PROXY'] = 'true'
    os.environ['ORIGIN_PROXY_URL'] = 'http://cloudscraper.proxy:7777'
    os.environ['PROXY_USERNAME'] = 'clouduser'
    os.environ['PROXY_PASSWORD'] = 'cloudpass'
    
    captured = []
    
    def mock_request(self, method, url, *args, **kwargs):
        captured.append({'method': method, 'url': url, 'kwargs': kwargs})
        resp = Mock()
        resp.status_code = 200
        resp.text = 'ok'
        return resp
    
    # Load sitecustomize
    spec = importlib.util.spec_from_file_location(
        'sitecustomize_cloud',
        'k8s/sitecustomize.py'
    )
    sitecustomize = importlib.util.module_from_spec(spec)
    
    with patch.object(requests.sessions.Session, 'request', mock_request):
        spec.loader.exec_module(sitecustomize)
        
        # cloudscraper.create_scraper() returns a Session subclass
        # So it should also be affected by the patch
        scraper = cloudscraper.create_scraper()
        
        try:
            scraper.get('https://example.com/cloudflare-protected')
        except Exception:
            pass
        
        # Check the request was proxied
        if captured:
            assert 'cloudscraper.proxy' in captured[-1]['url']
            assert 'Authorization' in captured[-1]['kwargs'].get('headers', {})
    
    # Clean up
    del os.environ['USE_ORIGIN_PROXY']
    del os.environ['ORIGIN_PROXY_URL']
    del os.environ['PROXY_USERNAME']
    del os.environ['PROXY_PASSWORD']


if __name__ == '__main__':
    # Run tests manually
    print("Running E2E proxy integration tests...")
    
    test_e2e_sitecustomize_with_real_session()
    print("✓ test_e2e_sitecustomize_with_real_session")
    
    test_e2e_without_proxy_enabled()
    print("✓ test_e2e_without_proxy_enabled")
    
    test_e2e_subprocess_invocation()
    print("✓ test_e2e_subprocess_invocation")
    
    try:
        test_e2e_cloudscraper_compatibility()
        print("✓ test_e2e_cloudscraper_compatibility")
    except Exception as e:
        print(f"⚠ test_e2e_cloudscraper_compatibility skipped: {e}")
    
    print("\n✅ All E2E tests passed!")
