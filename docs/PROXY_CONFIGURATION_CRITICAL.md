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
  name: squid-proxy-credentials
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
      name: squid-proxy-credentials
      key: selenium-proxy-url

# Optional: Override Decodo credentials (usually not needed)
# - name: DECODO_USERNAME
#   valueFrom:
#     secretKeyRef:
#       name: squid-proxy-credentials
#       key: decodo-username
# - name: DECODO_PASSWORD
#   valueFrom:
#     secretKeyRef:
#       name: squid-proxy-credentials
#       key: decodo-password
```

### What NOT to Do

```yaml
# ❌ NEVER DO THIS - Bypasses proxy switcher
- name: ORIGIN_PROXY_URL
  # CRITICAL: Proxy Configuration Rules

  ## ⚠️ NEVER HARDCODE PROXY URLS IN KUBERNETES DEPLOYMENTS

  ### The Problem (What Happened)

  The `k8s/processor-deployment.yaml` file once contained this:

  ```yaml
  # ❌ WRONG - Hardcoded proxy URL bypasses proxy switcher
  - name: SQUID_PROXY_URL
    value: "http://proxy.kiesow.net:23432"
  ```

  This caused:
  - **407 Proxy Authentication Required** errors when credentials rotated
  - **Bypassed the proxy switcher** (could not fail over to direct/backup)
  - Secret drift between environments (prod vs lab)
  - Hours wasted debugging why Squid config diverged from expectations

  ### The Solution (What We Fixed)

  ```yaml
  # ✅ CORRECT - Use PROXY_PROVIDER + secrets to manage proxies
  - name: PROXY_PROVIDER
    value: "squid"
  - name: SQUID_PROXY_URL
    valueFrom:
      secretKeyRef:
        name: squid-proxy-credentials
        key: url
  - name: SQUID_PROXY_USERNAME
    valueFrom:
      secretKeyRef:
        name: squid-proxy-credentials
        key: username
  - name: SQUID_PROXY_PASSWORD
    valueFrom:
      secretKeyRef:
        name: squid-proxy-credentials
        key: password
  ```

  The proxy switcher in `src/crawler/proxy_config.py` now:
  - Loads Squid credentials from environment variables/secrets
  - Constructs the correct authenticated proxy URL
  - Handles provider selection logic (squid, direct, standard, socks5...)
  - Allows instant switching without editing manifests

  Legacy Origin/Decodo adapters were removed—do **not** reintroduce them.

  ## How Proxy Selection Works

  ### 1. Environment Variable: PROXY_PROVIDER

  Controls which proxy provider to use:

  ```bash
  # Squid residential proxy (default, recommended)
  PROXY_PROVIDER=squid

  # Direct connection (no proxy)
  PROXY_PROVIDER=direct

  # Alternative providers (optional)
  PROXY_PROVIDER=standard        # STANDARD_PROXY_URL / USERNAME / PASSWORD
  PROXY_PROVIDER=socks5          # SOCKS5_* env vars
  PROXY_PROVIDER=brightdata      # BRIGHTDATA_* env vars
  PROXY_PROVIDER=scraper_api     # SCRAPERAPI_* env vars
  PROXY_PROVIDER=smartproxy      # SMARTPROXY_* env vars
  ```

  ### 2. Squid Credentials

  From `src/crawler/proxy_config.py`:

  ```python
  squid_url = os.getenv("SQUID_PROXY_URL", "http://t9880447.eero.online:3128")
  self.configs[ProxyProvider.SQUID] = ProxyConfig(
      provider=ProxyProvider.SQUID,
      enabled=bool(squid_url),
      url=squid_url,
      username=os.getenv("SQUID_PROXY_USERNAME"),
      password=os.getenv("SQUID_PROXY_PASSWORD"),
  )
  ```

  Set the URL + optional credentials via environment variables or Kubernetes secrets. If your Squid tier is IP-allowlisted you can omit username/password.

  ### 3. Kubernetes Secrets

  Use the shared `squid-proxy-credentials` secret everywhere:

  ```yaml
  apiVersion: v1
  kind: Secret
  metadata:
    name: squid-proxy-credentials
    namespace: production
  type: Opaque
  stringData:
    url: "http://squid.proxy.net:3128"
    username: "my-user"      # optional
    password: "my-password"  # optional
  ```

  Copy this secret between namespaces via `scripts/setup-lab-namespace.sh` (already implemented).

  ## Correct Kubernetes Deployment Pattern

  ### processor-deployment.yaml

  ```yaml
  env:
    # ✅ Use proxy switcher - DO NOT hardcode URLs/passwords
    - name: PROXY_PROVIDER
      value: "squid"
    - name: SQUID_PROXY_URL
      valueFrom:
        secretKeyRef:
          name: squid-proxy-credentials
          key: url
    - name: SQUID_PROXY_USERNAME
      valueFrom:
        secretKeyRef:
          name: squid-proxy-credentials
          key: username
          optional: true
    - name: SQUID_PROXY_PASSWORD
      valueFrom:
        secretKeyRef:
          name: squid-proxy-credentials
          key: password
          optional: true

    # Selenium proxy (separate system)
    - name: SELENIUM_PROXY
      valueFrom:
        secretKeyRef:
          name: squid-proxy-credentials
          key: selenium-proxy-url
          optional: true
  ```

  ### What NOT to Do

  ```yaml
  # ❌ NEVER DO THIS - Hardcoded URL/password
  - name: SQUID_PROXY_URL
    value: "http://user:pass@proxy.example.com:8080"

  # ❌ NEVER DO THIS - Bring back removed env vars
  - name: ORIGIN_PROXY_URL
    value: "http://proxy.kiesow.net:23432"

  # ❌ NEVER DO THIS - Reintroduce USE_ORIGIN_PROXY/DECODO_* env vars
  - name: USE_ORIGIN_PROXY
    value: "true"
  ```

  ## Switching Proxy Providers

  ### Quick Switch (No Rebuild)

  ```bash
  # Switch to Squid (recommended/default)
  kubectl set env deployment/mizzou-processor -n production PROXY_PROVIDER=squid

  # Temporary direct mode (troubleshooting only)
  kubectl set env deployment/mizzou-processor -n production PROXY_PROVIDER=direct

  # Verify current setting
  kubectl get deployment/mizzou-processor -n production -o yaml | grep PROXY_PROVIDER
  ```

  ### Permanent Change (In Code)

  Edit `k8s/processor-deployment.yaml` and update the `PROXY_PROVIDER` value (and accompanying env vars if using a different provider). Then rebuild/deploy as usual:

  ```bash
  git add k8s/processor-deployment.yaml
  git commit -m "chore: switch processor proxy provider"
  gcloud builds triggers run build-processor-manual --branch=<branch>
  ```

  ## Verification

  ### Check Active Proxy in Logs

  ```bash
  kubectl logs -n production deployment/mizzou-processor --tail=50 | grep -i squid
  ```

  Expected output:
  ```
  🔀 Proxy manager initialized with provider: squid
  🔀 Squid proxy enabled for HTTP extraction: http://squid.proxy.net:3128
  🔀 Proxying GET example.com via squid proxy
  ```

  ### Check Environment Variables

  ```bash
  kubectl exec -n production deployment/mizzou-processor -- env | grep -E "PROXY_PROVIDER|SQUID"
  ```

  Expected output:
  ```
  PROXY_PROVIDER=squid
  SQUID_PROXY_URL=http://squid.proxy.net:3128
  SQUID_PROXY_USERNAME=...
  SQUID_PROXY_PASSWORD=********
  ```

  There should be **no** `ORIGIN_PROXY_*`, `USE_ORIGIN_PROXY`, or `DECODO_*` env vars anywhere.

  ## Troubleshooting

  ### Issue: Still Using Wrong Proxy

  **Symptoms:**
  - Logs mention `proxy.kiesow.net` or other unexpected hosts
  - 407 authentication errors despite valid Squid credentials
  - `Proxy provider` log line shows `direct` when Squid should be active

  **Solution:**
  1. Inspect deployment:
     ```bash
     kubectl get deployment/mizzou-processor -n production -o yaml | grep -A3 SQUID_
     ```
     Ensure all `valueFrom` entries point to `squid-proxy-credentials`.
  2. Verify the secret contents (base64 decode) to ensure URL/credentials match expectations.
  3. Confirm `PROXY_PROVIDER` is set to `squid` (not inherited from an old ConfigMap).
  4. Restart the deployment after updating env vars to pick up new settings.

  ### Issue: Credential Rotation Broke Requests

  **Symptoms:**
  - 407 errors immediately after rotating Squid credentials
  - Logs show the old username

  **Solution:**
  - Update the `squid-proxy-credentials` secret with the new values
  - Restart any workloads that mount/env-ref the secret (`kubectl rollout restart deployment/mizzou-processor -n production`)
  - Re-run `python scripts/diagnose_proxy.py` to confirm connectivity

  ### Issue: Need Temporary Direct Mode

  ```bash
  kubectl set env deployment/mizzou-processor -n production PROXY_PROVIDER=direct
  # (do your testing)
  kubectl set env deployment/mizzou-processor -n production PROXY_PROVIDER=squid
  ```

  Never leave the deployment in direct mode—ensure Squid is restored.
