# CRITICAL: Proxy Configuration Rules

## ⚠️ NEVER HARDCODE PROXY URLS IN KUBERNETES DEPLOYMENTS

### The Problem (What Just Happened)

The `k8s/processor-deployment.yaml` file had this:

```yaml
# ❌ WRONG - Hardcoded proxy URL bypasses proxy switcher
- name: ORIGIN_PROXY_URL
  value: "http://proxy.kiesow.net:23432"
```

This caused:
- **407 Proxy Authentication Required** errors
- System using **wrong proxy** (kiesow.net instead of Decodo)
- **Bypassed the entire proxy switcher system**
- Wasted time debugging why Decodo wasn't being used

### The Solution (What We Fixed)

```yaml
# ✅ CORRECT - Use PROXY_PROVIDER to control which proxy
- name: PROXY_PROVIDER
  value: "decodo"
- name: USE_ORIGIN_PROXY
  value: "true"
```

The proxy switcher in `src/crawler/proxy_config.py` automatically:
- Loads Decodo credentials from environment or defaults
- Constructs proper proxy URL with auth
- Handles proxy selection logic
- Allows easy switching between providers

## How Proxy Selection Works

### 1. Environment Variable: PROXY_PROVIDER

Controls which proxy provider to use:

```bash
# Use Decodo ISP proxy (default, recommended)
PROXY_PROVIDER=decodo

# Use direct connection (no proxy)
PROXY_PROVIDER=direct

# Use old origin proxy (legacy, not recommended)
PROXY_PROVIDER=origin
```

### 2. Proxy Config Defaults

From `src/crawler/proxy_config.py`:

```python
# Decodo ISP proxy - ALWAYS AVAILABLE
decodo_username = os.getenv("DECODO_USERNAME", "your-decodo-username")
decodo_password = os.getenv("DECODO_PASSWORD", "your-decodo-password")
decodo_host = os.getenv("DECODO_HOST", "isp.decodo.com")
decodo_port = os.getenv("DECODO_PORT", "10000")
decodo_url = f"https://{decodo_username}:{decodo_password}@{decodo_host}:{decodo_port}"
```

**You don't need to set these unless overriding defaults.**

### 3. Kubernetes Secrets

Only needed if you want to override defaults or use different provider:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: origin-proxy-credentials
  namespace: production
type: Opaque
stringData:
  # Only if overriding Decodo defaults
  decodo-username: "user-custom"
  decodo-password: "custom-password"
  
  # For Selenium (separate)
  selenium-proxy-url: "http://proxy.example.com:8080"
```

## Correct Kubernetes Deployment Pattern

### processor-deployment.yaml

```yaml
env:
# ✅ Use proxy switcher - DO NOT hardcode ORIGIN_PROXY_URL
- name: PROXY_PROVIDER
  value: "decodo"  # or "direct", "origin", etc.
- name: USE_ORIGIN_PROXY
  value: "true"    # Enable proxy system

# Selenium proxy (separate system)
- name: SELENIUM_PROXY
  valueFrom:
    secretKeyRef:
      name: origin-proxy-credentials
      key: selenium-proxy-url

# Optional: Override Decodo credentials (usually not needed)
# - name: DECODO_USERNAME
#   valueFrom:
#     secretKeyRef:
#       name: origin-proxy-credentials
#       key: decodo-username
# - name: DECODO_PASSWORD
#   valueFrom:
#     secretKeyRef:
#       name: origin-proxy-credentials
#       key: decodo-password
```

### What NOT to Do

```yaml
# ❌ NEVER DO THIS - Bypasses proxy switcher
- name: ORIGIN_PROXY_URL
  value: "http://proxy.kiesow.net:23432"

# ❌ NEVER DO THIS - Hardcoded credentials
- name: ORIGIN_PROXY_URL
  value: "http://user:pass@proxy.example.com:8080"

# ❌ NEVER DO THIS - Overrides proxy config defaults
- name: ORIGIN_PROXY_URL
  valueFrom:
    secretKeyRef:
      name: some-secret
      key: proxy-url
```

## Switching Proxy Providers

### Quick Switch (No Rebuild)

```bash
# Switch to Decodo
kubectl set env deployment/mizzou-processor -n production PROXY_PROVIDER=decodo

# Switch to direct (no proxy)
kubectl set env deployment/mizzou-processor -n production PROXY_PROVIDER=direct

# Verify
kubectl get deployment/mizzou-processor -n production -o yaml | grep PROXY_PROVIDER
```

### Permanent Change (In Code)

Edit `k8s/processor-deployment.yaml`:

```yaml
- name: PROXY_PROVIDER
  value: "decodo"  # Change this value
```

Then commit and deploy:

```bash
git add k8s/processor-deployment.yaml
git commit -m "chore: Switch to <provider> proxy"
git push
gcloud builds triggers run build-processor-manual --branch=<branch>
```

## Verification

### Check Active Proxy in Logs

```bash
kubectl logs -n production deployment/mizzou-processor --tail=20 | grep -i proxy
```

Expected output:
```
🔀 Proxy manager initialized with provider: decodo
🔀 Standard proxy enabled: decodo (['http', 'https'])
🔀 Proxying GET example.com via decodo proxy
```

### Check Environment Variables

```bash
kubectl exec -n production deployment/mizzou-processor -- env | grep PROXY
```

Expected output:
```
PROXY_PROVIDER=decodo
USE_ORIGIN_PROXY=true
```

Should **NOT** see:
```
ORIGIN_PROXY_URL=http://proxy.kiesow.net:23432  # ❌ BAD
```

## Troubleshooting

### Issue: Still Using Wrong Proxy

**Symptoms:**
- Logs show `proxy.kiesow.net:23432`
- Getting 407 auth errors
- Wrong proxy provider in logs

**Solution:**
```bash
# 1. Check deployment YAML
kubectl get deployment/mizzou-processor -n production -o yaml | grep -A2 PROXY

# 2. If ORIGIN_PROXY_URL exists, it's wrong - rebuild
git pull
# Verify k8s/processor-deployment.yaml has PROXY_PROVIDER, not ORIGIN_PROXY_URL
gcloud builds triggers run build-processor-manual --branch=<branch>

# 3. Wait for new pod
kubectl rollout status deployment/mizzou-processor -n production
```

### Issue: Decodo Not Working

**Symptoms:**
- Connection timeouts
- DNS errors
- Auth failures

**Debug:**
```bash
# Check proxy config is loading
kubectl logs -n production deployment/mizzou-processor --tail=100 | grep -i decodo

# Check environment
kubectl exec -n production deployment/mizzou-processor -- python3 -c "
from src.crawler.proxy_config import ProxyManager
pm = ProxyManager()
print(f'Active: {pm.active_provider}')
print(f'Decodo config: {pm.configs.get(pm.active_provider)}')
"
```

## Adding New Proxy Provider

### 1. Add to proxy_config.py

```python
class ProxyProvider(Enum):
    # ... existing providers ...
    MY_NEW_PROXY = "my_new_proxy"

# In _load_configurations():
my_proxy_url = os.getenv("MY_PROXY_URL", "http://default.proxy.com:8080")
self.configs[ProxyProvider.MY_NEW_PROXY] = ProxyConfig(
    provider=ProxyProvider.MY_NEW_PROXY,
    enabled=True,
    url=my_proxy_url,
    username=os.getenv("MY_PROXY_USERNAME"),
    password=os.getenv("MY_PROXY_PASSWORD"),
)
```

### 2. Use in Deployment

```yaml
- name: PROXY_PROVIDER
  value: "my_new_proxy"
```

### 3. Test Locally

```bash
export PROXY_PROVIDER=my_new_proxy
export MY_PROXY_URL=http://test.proxy.com:8080
export MY_PROXY_USERNAME=testuser
export MY_PROXY_PASSWORD=testpass
python3 test_proxy.py
```

## Deployment Checklist

Before deploying processor:

- [ ] `k8s/processor-deployment.yaml` has `PROXY_PROVIDER` env var
- [ ] `k8s/processor-deployment.yaml` does NOT have `ORIGIN_PROXY_URL` env var
- [ ] `PROXY_PROVIDER` value matches desired proxy (usually "decodo")
- [ ] Commit message mentions proxy configuration
- [ ] After deploy, verify logs show correct proxy provider

## Emergency Rollback

If new proxy breaks extraction:

```bash
# Quick switch back to working proxy
kubectl set env deployment/mizzou-processor -n production PROXY_PROVIDER=direct

# Or switch to origin (if it was working)
kubectl set env deployment/mizzou-processor -n production PROXY_PROVIDER=origin

# Wait for rollout
kubectl rollout status deployment/mizzou-processor -n production

# Check logs
kubectl logs -n production deployment/mizzou-processor --tail=50 | grep -i proxy
```

## Related Files

- `src/crawler/proxy_config.py` - Proxy manager and provider definitions
- `src/crawler/origin_proxy.py` - Origin-style proxy implementation
- `src/crawler/__init__.py` - HTTP session creation with proxy
- `k8s/processor-deployment.yaml` - Kubernetes deployment config
- `k8s/api-deployment.yaml` - API deployment config
- `k8s/origin-sitecustomize-configmap.yaml` - Global proxy injection

## History

- **2025-10-11**: Fixed hardcoded `ORIGIN_PROXY_URL` in processor deployment
  - Issue: 407 errors, wrong proxy being used
  - Solution: Removed hardcoded URL, added `PROXY_PROVIDER=decodo`
  - Commit: 916d972
  - Never hardcode proxy URLs again!

- **2025-09-XX**: Added proxy switcher system
  - Multiple provider support
  - Easy switching via PROXY_PROVIDER
  - Default Decodo configuration

- **2025-08-XX**: Original origin proxy implementation
  - Single proxy (kiesow.net)
  - No provider abstraction
  - Led to hardcoding issues
