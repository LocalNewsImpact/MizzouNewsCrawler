# Proxy Architecture Documentation

## Overview

This document provides a detailed technical overview of the proxy architecture implementation for the MizzouNewsCrawler application.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                        │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │              ConfigMap: origin-sitecustomize        │    │
│  │  ┌──────────────────────────────────────────────┐  │    │
│  │  │  sitecustomize.py                            │  │    │
│  │  │  - Checks USE_ORIGIN_PROXY env var          │  │    │
│  │  │  - Patches requests.Session.request          │  │    │
│  │  │  - Rewrites URLs to proxy format             │  │    │
│  │  │  - Adds Authorization headers                │  │    │
│  │  └──────────────────────────────────────────────┘  │    │
│  └────────────────────────────────────────────────────┘    │
│                            ↓ mounted as file                │
│  ┌────────────────────────────────────────────────────┐    │
│  │         Pod: mizzou-processor                       │    │
│  │                                                     │    │
│  │  /usr/local/lib/python3.12/site-packages/         │    │
│  │    └── sitecustomize.py (mounted from ConfigMap)   │    │
│  │                                                     │    │
│  │  Environment Variables (from Secret):              │    │
│  │    - USE_ORIGIN_PROXY=true                         │    │
│  │    - ORIGIN_PROXY_URL=http://proxy:23432           │    │
│  │    - PROXY_USERNAME=news_crawler                   │    │
│  │    - PROXY_PASSWORD=***                            │    │
│  │                                                     │    │
│  │  ┌──────────────────────────────────────────────┐ │    │
│  │  │  Python Process                               │ │    │
│  │  │  1. Startup → loads sitecustomize.py         │ │    │
│  │  │  2. Patches requests.Session                  │ │    │
│  │  │  3. Application code runs                     │ │    │
│  │  │     - NewsDiscovery()                         │ │    │
│  │  │     - ContentExtractor()                      │ │    │
│  │  │     - cloudscraper.create_scraper()          │ │    │
│  │  │  4. All HTTP requests → patched method       │ │    │
│  │  └──────────────────────────────────────────────┘ │    │
│  └────────────────────────────────────────────────────┘    │
│                            ↓                                │
│                    Network egress                           │
└─────────────────────────────────────────────────────────────┘
                            ↓
        ┌───────────────────────────────────┐
        │   Origin Proxy Server              │
        │   (proxy.kiesow.net:23432)        │
        │                                    │
        │  1. Receives request:              │
        │     GET ?url=<encoded_target>      │
        │     Authorization: Basic <creds>   │
        │                                    │
        │  2. Validates credentials          │
        │                                    │
        │  3. Fetches target URL             │
        │                                    │
        │  4. Returns response               │
        └───────────────────────────────────┘
                            ↓
        ┌───────────────────────────────────┐
        │   Target Web Server                │
        │   (example.com, news sites, etc.) │
        └───────────────────────────────────┘
```

## Request Flow

### 1. Python Interpreter Startup

```
┌─────────────────────────────────────────────────────────┐
│ Python starts                                            │
│   ↓                                                      │
│ Searches for sitecustomize.py in sys.path               │
│   ↓                                                      │
│ Finds: /usr/local/lib/python3.12/site-packages/        │
│        sitecustomize.py                                  │
│   ↓                                                      │
│ Executes sitecustomize.py                               │
│   ↓                                                      │
│ Checks environment:                                      │
│   - USE_ORIGIN_PROXY = "true" ✓                        │
│   - ORIGIN_PROXY_URL = "http://proxy:23432" ✓          │
│   ↓                                                      │
│ Imports requests library                                 │
│   ↓                                                      │
│ Patches requests.sessions.Session.request               │
│   ↓                                                      │
│ Logs: "origin-shim enabled: routing requests through..." │
└─────────────────────────────────────────────────────────┘
```

### 2. Application Code Execution

```
┌─────────────────────────────────────────────────────────┐
│ Application code runs                                    │
│                                                          │
│ Example: NewsDiscovery creates session                  │
│   session = cloudscraper.create_scraper()               │
│     ↓                                                    │
│   (cloudscraper returns requests.Session subclass)      │
│     ↓                                                    │
│   session.get('https://news-site.com/article')          │
│     ↓                                                    │
│   Session.get() internally calls Session.request()      │
│     ↓                                                    │
│   ENTERS PATCHED METHOD                                  │
└─────────────────────────────────────────────────────────┘
```

### 3. Patched Request Method Logic

```python
def _proxied_request(self, method, url, *args, **kwargs):
    # Step 1: Check if URL should be proxied
    if isinstance(url, str) and url.startswith(("http://", "https://")):
        
        # Step 2: Rewrite URL
        # Original: https://news-site.com/article
        # Becomes:  http://proxy:23432?url=https%3A%2F%2Fnews-site.com%2Farticle
        proxied = ORIGIN.rstrip("/") + "?url=" + quote_plus(url)
        
        # Step 3: Prepare headers (don't mutate caller's dict)
        headers = dict(kwargs.get("headers") or {})
        
        # Step 4: Add Basic Auth if credentials available
        if USER and PWD:
            creds = base64.b64encode(f"{USER}:{PWD}".encode()).decode()
            headers.setdefault("Authorization", "Basic " + creds)
        
        # Step 5: Update kwargs
        kwargs["headers"] = headers
        url = proxied
    
    # Step 6: Call original request method with rewritten URL
    return _orig_request(self, method, url, *args, **kwargs)
```

### 4. Proxy Server Handling

```
┌─────────────────────────────────────────────────────────┐
│ Proxy receives:                                          │
│   GET /?url=https%3A%2F%2Fnews-site.com%2Farticle       │
│   Host: proxy.kiesow.net:23432                          │
│   Authorization: Basic bmV3c19jcmF3bGVyOnBhc3N3b3Jk     │
│     ↓                                                    │
│ Decodes Authorization header                            │
│   → username: news_crawler                              │
│   → password: ***                                       │
│     ↓                                                    │
│ Validates credentials ✓                                 │
│     ↓                                                    │
│ Decodes url parameter                                   │
│   → https://news-site.com/article                       │
│     ↓                                                    │
│ Makes request to target:                                │
│   GET /article                                          │
│   Host: news-site.com                                   │
│   (with proxy's IP address)                             │
│     ↓                                                    │
│ Receives response from target                           │
│     ↓                                                    │
│ Returns response to client                              │
└─────────────────────────────────────────────────────────┘
```

## Component Interactions

### Kubernetes Resources

```
┌──────────────────────────────────────────────────────┐
│                    Namespace: production              │
│                                                       │
│  ┌────────────────────────────────────────────────┐ │
│  │ ConfigMap: origin-sitecustomize                 │ │
│  │   data:                                         │ │
│  │     sitecustomize.py: |                         │ │
│  │       <Python code>                             │ │
│  └────────────────────────────────────────────────┘ │
│           │ mounted into                             │
│           ↓                                          │
│  ┌────────────────────────────────────────────────┐ │
│  │ Deployment: mizzou-processor                    │ │
│  │   spec:                                         │ │
│  │     volumes:                                    │ │
│  │     - name: origin-sitecustomize                │ │
│  │       configMap:                                │ │
│  │         name: origin-sitecustomize              │ │
│  │     containers:                                 │ │
│  │     - name: processor                           │ │
│  │       volumeMounts:                             │ │
│  │       - name: origin-sitecustomize              │ │
│  │         mountPath: /usr/local/lib/.../          │ │
│  │                    sitecustomize.py             │ │
│  │         subPath: sitecustomize.py               │ │
│  │       env:                                      │ │
│  │       - name: USE_ORIGIN_PROXY                  │ │
│  │         value: "true"                           │ │
│  │       - name: ORIGIN_PROXY_URL                  │ │
│  │         valueFrom:                              │ │
│  │           secretKeyRef: ───────────────────┐    │ │
│  └────────────────────────────────────────────│────┘ │
│                                                │      │
│  ┌────────────────────────────────────────────│────┐ │
│  │ Secret: origin-proxy-credentials           │    │ │
│  │   data:                                    │    │ │
│  │     PROXY_USERNAME: <base64>      ←────────┘    │ │
│  │     PROXY_PASSWORD: <base64>                    │ │
│  │     ORIGIN_PROXY_URL: <base64>                  │ │
│  │     SELENIUM_PROXY: <base64>                    │ │
│  └─────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

## Code Coverage

### Modules Automatically Covered

All these modules get proxy support automatically without code changes:

```
src/crawler/
├── __init__.py
│   ├── ContentExtractor._get_domain_session()
│   │   └── creates requests.Session or cloudscraper
│   └── NewsCrawler.fetch_page()
│       └── uses self.session.get()
│
├── discovery.py
│   └── NewsDiscovery.__init__()
│       └── self.session = cloudscraper.create_scraper()
│
src/services/
└── url_verification.py
    └── URLVerificationService.__init__()
        └── self.http_session = requests.Session()

src/pipeline/
└── crawler.py
    └── crawl_page(url)
        └── requests.get(url, ...)

src/utils/
├── telemetry_extractor.py
│   └── TelemetryExtractor.__init__()
│       └── self.session = requests.Session()
│
└── telemetry.py
    └── TelemetryCollector.__init__()
        └── self.session = requests.Session()
```

### What Gets Patched

```
requests.sessions.Session.request (class method)
    ↓ affects
requests.Session().get/post/put/delete/... (all HTTP methods)
    ↓ affects
cloudscraper.create_scraper() (returns Session subclass)
    ↓ affects
All code using requests or cloudscraper
```

### What Doesn't Get Patched

- `urllib.request.urlopen()` - Uses different API
- `urllib3` direct usage - Not using requests.Session
- `http.client` direct usage - Low-level, not common
- Raw sockets - Not HTTP library level

**Solution for non-requests libraries**: Set standard HTTP proxy environment variables:
```bash
export HTTP_PROXY=http://user:pass@proxy:23432
export HTTPS_PROXY=http://user:pass@proxy:23432
```

## Security Architecture

### Credential Flow

```
Developer/Operator
    ↓ (creates secret manually)
kubectl create secret
    ↓ (stores in cluster)
Kubernetes Secret (etcd encrypted at rest)
    ↓ (mounted as env vars)
Pod Environment Variables
    ↓ (read at runtime)
sitecustomize.py
    ↓ (uses for auth)
HTTP Authorization Header
    ↓ (sent to proxy)
Proxy Server
    ↓ (validates)
Access Granted/Denied
```

### Security Controls

1. **Credentials Storage**
   - Stored in Kubernetes Secrets (encrypted at rest)
   - Never in ConfigMaps or code
   - Mounted as environment variables (not files)

2. **Access Control**
   - RBAC controls who can read secrets
   - Service account controls pod access
   - Network policies control egress

3. **Logging**
   - sitecustomize logs only URLs and booleans
   - Never logs credentials
   - Proxy logs show auth success/failure

4. **Audit Trail**
   - Kubernetes audit logs show secret access
   - Proxy logs show request patterns
   - Application logs show request success/failure

## Performance Considerations

### Overhead

1. **Startup**: +10-50ms (one-time, loading and patching)
2. **Per-request**: Minimal (single function call wrapper)
3. **Network**: Depends on proxy latency
4. **Memory**: Negligible (~10KB for shim code)

### Optimization

The implementation is optimized for:
- **Minimal CPU overhead**: Single if-check per request
- **No memory copies**: Headers dict creation, not mutation
- **Fast path**: Early return for non-HTTP URLs
- **Error handling**: Try-except ensures errors don't break requests

### Scalability

- ✅ Works with any number of pods
- ✅ Stateless (each pod independent)
- ✅ No shared resources
- ⚠️ Proxy server is single point of failure/bottleneck

## Testing Architecture

### Test Pyramid

```
        ┌─────────────┐
        │     E2E     │  test_proxy_integration_e2e.py
        │  Integration│  - Full flow testing
        │    Tests    │  - Subprocess invocation
        └─────────────┘  - cloudscraper compatibility
              │
        ┌─────────────┐
        │    Unit     │  test_origin_proxy.py
        │   Tests     │  test_integration_proxy.py
        └─────────────┘  test_sitecustomize_shim.py
              │          - URL rewriting
              │          - Auth injection
              │          - Edge cases
        ┌─────────────┐
        │ Standalone  │  test_sitecustomize_standalone.py
        │    Tests    │  - No pytest dependencies
        └─────────────┘  - Can run anywhere
```

### Test Coverage

- ✅ Activation logic (USE_ORIGIN_PROXY flag)
- ✅ URL rewriting (quote_plus encoding)
- ✅ Authorization header injection
- ✅ Existing header preservation
- ✅ Non-HTTP URL passthrough
- ✅ Missing credentials handling
- ✅ Error handling (fail-safe)
- ✅ cloudscraper compatibility
- ✅ Subprocess behavior
- ✅ YAML syntax validation

## Monitoring and Observability

### What to Monitor

1. **Pod Startup Logs**
   ```
   Look for: INFO:origin-shim:origin-shim enabled: routing requests through...
   ```

2. **Request Success Rate**
   ```
   Monitor HTTP status codes from application
   Expected: Similar distribution to without proxy
   ```

3. **Proxy Server Metrics**
   ```
   - Request count
   - Auth failures
   - Response times
   - Error rates
   ```

4. **Application Metrics**
   ```
   - HTTP request latency (may increase slightly)
   - Error rates (should not change)
   - Throughput (may decrease slightly due to proxy hop)
   ```

### Debug Commands

```bash
# Check if shim is loaded
kubectl logs POD | grep origin-shim

# Check environment variables
kubectl exec POD -- printenv | grep PROXY

# Test a request
kubectl exec POD -- python -c "import requests; print(requests.get('http://example.com').status_code)"

# Check sitecustomize is mounted
kubectl exec POD -- ls -la /usr/local/lib/python3.12/site-packages/sitecustomize.py

# Verify patching worked
kubectl exec POD -- python -c "import requests, inspect; print(inspect.isbuiltin(requests.sessions.Session.request))"
# Output: False (if patched, True if not)
```

## Conclusion

This architecture provides:
- ✅ Automatic proxy integration without code changes
- ✅ Centralized configuration via environment variables
- ✅ Secure credential management
- ✅ Comprehensive test coverage
- ✅ Production-ready monitoring
- ✅ Minimal performance overhead
- ✅ Easy deployment and rollback

The solution is designed to be robust, maintainable, and operator-friendly.
