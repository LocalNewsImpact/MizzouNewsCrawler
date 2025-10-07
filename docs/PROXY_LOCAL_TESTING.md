# Local Proxy Testing Guide

This guide explains how to test the proxy functionality locally without deploying to Kubernetes.

## Prerequisites

- Python 3.9+
- Access to the proxy server (or a test proxy)
- Proxy credentials

## Option 1: Using Environment Variables

The simplest way to test locally is to set environment variables before running Python:

```bash
# Set proxy configuration
export USE_ORIGIN_PROXY=true
export ORIGIN_PROXY_URL=http://proxy.kiesow.net:23432
export PROXY_USERNAME=news_crawler
export PROXY_PASSWORD=your_password

# Copy sitecustomize to your local Python site-packages
SITE_PACKAGES=$(python -c "import site; print(site.getsitepackages()[0])")
echo "Copying to: $SITE_PACKAGES"
sudo cp k8s/sitecustomize.py "$SITE_PACKAGES/"

# Run your application
python orchestration/continuous_processor.py
```

## Option 2: Manual Integration (No sitecustomize)

If you prefer not to install sitecustomize.py globally, you can manually enable the proxy in your code:

```python
import os
import requests
from src.crawler.origin_proxy import enable_origin_proxy

# Set environment variables in code (or load from .env)
os.environ['USE_ORIGIN_PROXY'] = 'true'
os.environ['ORIGIN_PROXY_URL'] = 'http://proxy.kiesow.net:23432'
os.environ['PROXY_USERNAME'] = 'news_crawler'
os.environ['PROXY_PASSWORD'] = 'your_password'

# Create a session and enable proxy
session = requests.Session()
enable_origin_proxy(session)

# Use the session
response = session.get('https://example.com')
print(f'Status: {response.status_code}')
```

## Option 3: Using a Test Proxy Server

For development, you can run a local test proxy:

```bash
# Install a simple proxy server
pip install mitmproxy

# Run it
mitmproxy -p 8080

# In another terminal, set env vars to use it
export USE_ORIGIN_PROXY=true
export ORIGIN_PROXY_URL=http://localhost:8080
export PROXY_USERNAME=testuser
export PROXY_PASSWORD=testpass
```

## Testing Without a Real Proxy

If you don't have access to the actual proxy server, you can test the URL rewriting logic:

```python
import os
import sys
from unittest.mock import Mock, patch
from urllib.parse import quote_plus

# Set up environment
os.environ['USE_ORIGIN_PROXY'] = 'true'
os.environ['ORIGIN_PROXY_URL'] = 'http://fake.proxy:9999'
os.environ['PROXY_USERNAME'] = 'testuser'
os.environ['PROXY_PASSWORD'] = 'testpass'

# Track requests
captured = []

def mock_request(self, method, url, *args, **kwargs):
    captured.append({
        'method': method,
        'url': url,
        'kwargs': kwargs
    })
    resp = Mock()
    resp.status_code = 200
    resp.text = 'mock response'
    return resp

# Patch and test
import requests
from requests.sessions import Session

with patch.object(Session, 'request', mock_request):
    # Load sitecustomize
    import importlib.util
    spec = importlib.util.spec_from_file_location('sitecustomize', 'k8s/sitecustomize.py')
    sitecustomize = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sitecustomize)
    
    # Make a test request
    session = requests.Session()
    response = session.get('https://example.com/test')
    
    # Verify
    print(f"Captured URL: {captured[-1]['url']}")
    print(f"Expected proxy URL: http://fake.proxy:9999?url={quote_plus('https://example.com/test')}")
    
    assert 'fake.proxy' in captured[-1]['url']
    assert 'Authorization' in captured[-1]['kwargs'].get('headers', {})
    print("✓ Proxy rewriting works!")
```

## Running Tests Locally

```bash
# Run standalone tests (no pytest required)
python tests/test_sitecustomize_standalone.py

# Run E2E integration tests
python tests/test_proxy_integration_e2e.py

# Run pytest tests (requires pytest)
python -m pytest tests/test_origin_proxy.py -v
python -m pytest tests/test_integration_proxy.py -v
```

## Testing Specific Components

### Test URL Rewriting

```python
from urllib.parse import quote_plus

url = "https://example.com/path?foo=bar"
proxy_base = "http://proxy.kiesow.net:23432"
proxied = proxy_base.rstrip("/") + "?url=" + quote_plus(url)

print(f"Original: {url}")
print(f"Proxied:  {proxied}")
# Output: http://proxy.kiesow.net:23432?url=https%3A%2F%2Fexample.com%2Fpath%3Ffoo%3Dbar
```

### Test Auth Header

```python
import base64

username = "news_crawler"
password = "your_password"
creds = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
auth_header = f"Basic {creds}"

print(f"Authorization: {auth_header}")
```

### Test with cloudscraper

```python
import os
os.environ['USE_ORIGIN_PROXY'] = 'true'
os.environ['ORIGIN_PROXY_URL'] = 'http://proxy.kiesow.net:23432'
os.environ['PROXY_USERNAME'] = 'news_crawler'
os.environ['PROXY_PASSWORD'] = 'your_password'

# Load sitecustomize first
import importlib.util
spec = importlib.util.spec_from_file_location('sitecustomize', 'k8s/sitecustomize.py')
sitecustomize = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sitecustomize)

# Now use cloudscraper
import cloudscraper
scraper = cloudscraper.create_scraper()
response = scraper.get('https://example.com')
print(f'Status: {response.status_code}')
```

## Debugging

### Enable Verbose Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# The origin-shim will log when it activates
import importlib.util
spec = importlib.util.spec_from_file_location('sitecustomize', 'k8s/sitecustomize.py')
sitecustomize = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sitecustomize)
```

### Check If Shim Is Active

```python
import requests
import inspect

# Check if Session.request was patched
is_patched = not inspect.isbuiltin(requests.sessions.Session.request)
print(f"Session.request patched: {is_patched}")

# Check if session has the _origin_proxy_installed attribute
session = requests.Session()
has_flag = hasattr(session, '_origin_proxy_installed')
print(f"Has _origin_proxy_installed: {has_flag}")
```

### Test Direct Proxy Connection

```bash
# Test if you can reach the proxy directly
curl -v "http://proxy.kiesow.net:23432?url=http%3A%2F%2Fexample.com" \
  -u "news_crawler:your_password"

# Expected: 200 OK with content from example.com
```

## Common Issues

### ImportError: No module named 'requests'

Solution: Install requests
```bash
pip install requests
```

### Permission denied when copying sitecustomize.py

Solution: Use sudo or copy to user site-packages
```bash
# User site-packages (no sudo needed)
USER_SITE=$(python -m site --user-site)
mkdir -p "$USER_SITE"
cp k8s/sitecustomize.py "$USER_SITE/"
```

### Proxy connection refused

Check:
1. Proxy server is running and accessible
2. Firewall allows connections to proxy port
3. Proxy URL is correct (including port)

### Authentication fails

Check:
1. Username and password are correct
2. No typos in environment variables
3. Password doesn't need URL encoding (for ORIGIN_PROXY_URL, plain password is fine)

## Cleanup

When done testing, remove sitecustomize.py:

```bash
# Find where it was installed
python -c "import site; print(site.getsitepackages()[0])"

# Remove it (may need sudo)
sudo rm /path/to/site-packages/sitecustomize.py

# Or if installed in user site-packages
rm $(python -m site --user-site)/sitecustomize.py

# Unset environment variables
unset USE_ORIGIN_PROXY ORIGIN_PROXY_URL PROXY_USERNAME PROXY_PASSWORD
```

## Next Steps

After successful local testing:
1. Review [docs/PROXY_DEPLOYMENT_GUIDE.md](PROXY_DEPLOYMENT_GUIDE.md) for Kubernetes deployment
2. Use [PROXY_DEPLOYMENT_CHECKLIST.md](../PROXY_DEPLOYMENT_CHECKLIST.md) for production deployment
3. Run [scripts/validate_proxy_deployment.sh](../scripts/validate_proxy_deployment.sh) to validate deployment
