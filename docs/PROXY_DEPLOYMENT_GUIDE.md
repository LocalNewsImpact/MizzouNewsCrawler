# Proxy Deployment Guide

This guide explains how to deploy the origin-style proxy adapter to ensure all HTTP clients in the crawler application route through the proxy.

## Overview

The proxy solution uses a global `sitecustomize.py` shim that automatically patches `requests.Session` at Python interpreter startup. This ensures:

- **Universal coverage**: All HTTP clients (requests, cloudscraper, feedparser when using requests) are automatically proxied
- **No code changes needed**: Works with existing code without modifications
- **Configurable**: Enable/disable via environment variables
- **Fail-safe**: Errors in the shim don't break requests

## Architecture

```
┌─────────────────────────────────────────────────┐
│ Python Interpreter Startup                      │
│ ┌─────────────────────────────────────────────┐ │
│ │ sitecustomize.py loaded automatically       │ │
│ │ - Checks USE_ORIGIN_PROXY env var           │ │
│ │ - Patches requests.Session.request          │ │
│ └─────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│ Application Code                                 │
│ - ContentExtractor creates requests.Session     │
│ - NewsDiscovery creates cloudscraper.Session    │
│ - All HTTP requests automatically proxied       │
└─────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│ Origin Proxy (proxy.kiesow.net:23432)           │
│ - Receives: GET http://proxy?url=<target>       │
│ - Authenticates via Basic Auth header           │
│ - Fetches target URL and returns response       │
└─────────────────────────────────────────────────┘
```

## Components

### 1. sitecustomize.py
- Location: `k8s/sitecustomize.py`
- Deployed via ConfigMap to pods
- Mounted at: `/usr/local/lib/python3.12/site-packages/sitecustomize.py`

### 2. ConfigMap
- File: `k8s/origin-sitecustomize-configmap.yaml`
- Contains the sitecustomize.py code
- Deployed to `production` namespace

### 3. Secret
- Template: `k8s/origin-proxy-secret.yaml.template`
- Contains proxy credentials and URLs
- Must be created with actual credentials (see below)

### 4. Deployment Updates
- `k8s/processor-deployment.yaml`: Updated with volume mount and env vars
- `k8s/crawler-cronjob.yaml`: Updated with volume mount and env vars

## Deployment Steps

### Step 1: Determine the site-packages Path

Before deploying, you need to find the correct Python site-packages path in your container image.

```bash
# Pick a running pod (or start one temporarily)
NAMESPACE=production
POD=$(kubectl get pods -n $NAMESPACE -o name | grep -i processor | head -n1 | sed 's#pod/##')

# Query the Python site-packages paths
kubectl exec -n $NAMESPACE -it $POD -- python -c "
import site
print('site.getsitepackages():', site.getsitepackages())
"
```

Example output:
```
site.getsitepackages(): ['/usr/local/lib/python3.12/site-packages']
```

**Update the deployment files** with the correct path if it differs from `/usr/local/lib/python3.12/site-packages`.

### Step 2: Create the Proxy Credentials Secret

⚠️ **DO NOT commit actual credentials to git**

```bash
# Encode the proxy password for URL embedding (for Selenium)
python3 -c "
import urllib.parse
password = 'YOUR_ACTUAL_PASSWORD'  # Replace with actual password
print('URL-encoded password:', urllib.parse.quote(password, safe=''))
"

# Create the secret (replace placeholders)
kubectl create secret generic origin-proxy-credentials \
  --namespace=production \
  --from-literal=PROXY_USERNAME='news_crawler' \
  --from-literal=PROXY_PASSWORD='YOUR_ACTUAL_PASSWORD' \
  --from-literal=ORIGIN_PROXY_URL='http://proxy.kiesow.net:23432' \
  --from-literal=SELENIUM_PROXY='http://news_crawler:URL_ENCODED_PASSWORD@proxy.kiesow.net:23432'
```

To verify the secret was created:
```bash
kubectl get secret origin-proxy-credentials -n production -o yaml
```

### Step 3: Deploy the ConfigMap

```bash
# Apply the sitecustomize ConfigMap
kubectl apply -f k8s/origin-sitecustomize-configmap.yaml
```

Verify:
```bash
kubectl get configmap origin-sitecustomize -n production
```

### Step 4: Update and Deploy the Processor

```bash
# Apply the updated processor deployment
kubectl apply -f k8s/processor-deployment.yaml

# Rollout restart to pick up the changes
kubectl rollout restart deployment/mizzou-processor -n production
kubectl rollout status deployment/mizzou-processor -n production
```

### Step 5: Update and Deploy the Crawler CronJob

```bash
# Apply the updated crawler cronjob
kubectl apply -f k8s/crawler-cronjob.yaml
```

The next scheduled run will use the proxy.

## Verification

### Verify ConfigMap is Mounted

```bash
POD=$(kubectl get pods -n production -l app=mizzou-processor -o name | head -n1 | sed 's#pod/##')

# Check if sitecustomize.py is present
kubectl exec -n production -it $POD -- ls -la /usr/local/lib/python3.12/site-packages/sitecustomize.py

# View the file content
kubectl exec -n production -it $POD -- cat /usr/local/lib/python3.12/site-packages/sitecustomize.py | head -20
```

### Verify Environment Variables

```bash
kubectl exec -n production -it $POD -- printenv | grep -E "PROXY|ORIGIN"
```

Expected output should show:
```
USE_ORIGIN_PROXY=true
ORIGIN_PROXY_URL=http://proxy.kiesow.net:23432
PROXY_USERNAME=news_crawler
PROXY_PASSWORD=***
```

### Test the Shim is Active

```bash
# Test that sitecustomize is loaded
kubectl exec -n production -it $POD -- python -c "
import logging
logging.basicConfig(level=logging.INFO)
# This will trigger sitecustomize loading
import requests
print('Requests module loaded')
"
```

Look for log output like:
```
INFO:origin-shim:origin-shim enabled: routing requests through http://proxy.kiesow.net:23432
```

### Test a Request

```bash
kubectl exec -n production -it $POD -- python -c "
import requests
try:
    response = requests.get('http://example.com', timeout=10)
    print(f'Status: {response.status_code}')
    print('Proxy is working!' if response.ok else 'Request failed')
except Exception as e:
    print(f'Error: {e}')
"
```

### Check Proxy Logs

On the proxy server (proxy.kiesow.net), check logs to confirm requests are coming through:

```bash
# SSH to proxy server
ssh opal19

# Tail the proxy logs
tail -f ~/apps/proxy-port/logs/proxy-port.log
```

You should see entries like:
```
[timestamp] Auth-check OK for news_crawler
[timestamp] Proxying: http://example.com
```

## Environment Variables

The following environment variables control proxy behavior:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `USE_ORIGIN_PROXY` | Yes | `false` | Set to `true`, `1`, or `yes` to enable |
| `ORIGIN_PROXY_URL` | Yes | - | Origin proxy URL (e.g., `http://proxy.kiesow.net:23432`) |
| `PROXY_USERNAME` | Optional | - | Basic auth username for proxy |
| `PROXY_PASSWORD` | Optional | - | Basic auth password for proxy |
| `SELENIUM_PROXY` | Optional | - | Proxy URL with embedded credentials for Selenium/Chrome |

## Disabling the Proxy

To disable the proxy without redeploying:

```bash
# Set USE_ORIGIN_PROXY to false
kubectl set env deployment/mizzou-processor USE_ORIGIN_PROXY=false -n production

# Restart the deployment
kubectl rollout restart deployment/mizzou-processor -n production
```

## Troubleshooting

### Proxy Not Working

1. **Check if sitecustomize is mounted**:
   ```bash
   kubectl exec -n production -it $POD -- ls -la /usr/local/lib/python3.12/site-packages/sitecustomize.py
   ```

2. **Check environment variables**:
   ```bash
   kubectl exec -n production -it $POD -- printenv | grep PROXY
   ```

3. **Check pod logs for shim messages**:
   ```bash
   kubectl logs -n production $POD | grep origin-shim
   ```

### Wrong site-packages Path

If Python is not loading sitecustomize.py:

1. Query the actual site-packages path in the pod
2. Update the `mountPath` in the deployment YAML
3. Reapply and restart

### Requests Failing

1. **Verify proxy is reachable**:
   ```bash
   kubectl exec -n production -it $POD -- curl -v http://proxy.kiesow.net:23432
   ```

2. **Test with explicit credentials**:
   ```bash
   kubectl exec -n production -it $POD -- curl -v \
     -u "news_crawler:PASSWORD" \
     "http://proxy.kiesow.net:23432?url=http://example.com"
   ```

3. **Check proxy server logs** for error messages

## Security Considerations

- **Secrets**: Store credentials in Kubernetes Secrets, never in code or ConfigMaps
- **RBAC**: Ensure only authorized service accounts can access the secrets
- **Network Policies**: Restrict pod egress to only allow proxy traffic
- **Audit**: Monitor proxy logs for unusual activity
- **Rotation**: Rotate proxy credentials periodically

## Rollback

If issues occur, rollback to the previous deployment:

```bash
kubectl rollout undo deployment/mizzou-processor -n production
kubectl rollout status deployment/mizzou-processor -n production
```

Or disable the proxy:

```bash
kubectl set env deployment/mizzou-processor USE_ORIGIN_PROXY=false -n production
```

## Additional Notes

### Selenium/Chrome Integration

The `SELENIUM_PROXY` environment variable provides proxy credentials for Chrome's CONNECT tunnel (for HTTPS). The format must include URL-encoded credentials:

```
http://username:url_encoded_password@proxy.host:port
```

This is automatically passed to Chrome via the `--proxy-server` option.

### feedparser Support

If feedparser uses urllib instead of requests internally, it won't be automatically proxied by the sitecustomize shim. To proxy feedparser:

1. Set standard proxy environment variables:
   ```bash
   HTTP_PROXY=http://user:pass@proxy.kiesow.net:23432
   HTTPS_PROXY=http://user:pass@proxy.kiesow.net:23432
   ```

2. Or wrap feedparser calls with the origin proxy explicitly in code.

### Local Testing

To test locally without Kubernetes:

```bash
# Set environment variables
export USE_ORIGIN_PROXY=true
export ORIGIN_PROXY_URL=http://proxy.kiesow.net:23432
export PROXY_USERNAME=news_crawler
export PROXY_PASSWORD=your_password

# Copy sitecustomize to your local site-packages
cp k8s/sitecustomize.py $(python -c "import site; print(site.getsitepackages()[0])")/

# Run your application
python orchestration/continuous_processor.py
```

## References

- Issue: [#54 - Global Proxy Adapter Integration](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/54)
- Origin Proxy Module: `src/crawler/origin_proxy.py`
- Tests: `tests/test_origin_proxy.py`, `tests/test_sitecustomize_shim.py`
