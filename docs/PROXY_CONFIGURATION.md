# Multi-Proxy Configuration System

**Status:** ✅ Implemented
**Date:** October 10, 2025
**Branch:** feature/gcp-kubernetes-deployment

---

## Overview

This system provides flexible proxy configuration with support for multiple providers and a master switch to easily change between them. All proxy routing is controlled via environment variables, allowing instant switching without code changes.

## Features

- ✅ **Multiple Proxy Providers** - Support for 7+ different proxy types
- ✅ **Master Switch** - Change providers with single environment variable
- ✅ **Health Monitoring** - Track success rates and response times
- ✅ **CLI Management** - Commands to list, switch, and test proxies
- ✅ **Zero Downtime** - Switch providers without restarting services
- ✅ **Backwards Compatible** - Existing origin proxy still works

---

## Supported Proxy Providers

### 1. Squid Proxy (Default)
**Current production proxy** - authenticated Squid tier

```bash
PROXY_PROVIDER=squid
SQUID_PROXY_URL=http://squid.proxy.net:3128
SQUID_PROXY_USERNAME=your_username   # optional
SQUID_PROXY_PASSWORD=your_password   # optional
```

### 2. Direct (No Proxy)
**Disable all proxying** - Direct connections

```bash
PROXY_PROVIDER=direct
```

### 3. Standard HTTP/HTTPS Proxy
**Traditional proxy server**

```bash
PROXY_PROVIDER=standard
STANDARD_PROXY_URL=http://proxy.example.com:8080
STANDARD_PROXY_USERNAME=user
STANDARD_PROXY_PASSWORD=pass
```

### 4. SOCKS5 Proxy
**SOCKS5 protocol support**

```bash
PROXY_PROVIDER=socks5
SOCKS5_PROXY_URL=socks5://proxy.example.com:1080
SOCKS5_PROXY_USERNAME=user
SOCKS5_PROXY_PASSWORD=pass
```

### 5. ScraperAPI
**Managed scraping service** - https://www.scraperapi.com/

```bash
PROXY_PROVIDER=scraperapi
SCRAPERAPI_KEY=your_api_key
SCRAPERAPI_RENDER=false  # Set to true for JS rendering
SCRAPERAPI_COUNTRY=us    # Target country
```

### 6. BrightData (Luminati)
**Premium residential proxies** - https://brightdata.com/

```bash
PROXY_PROVIDER=brightdata
BRIGHTDATA_PROXY_URL=http://proxy.brightdata.com:22225
BRIGHTDATA_USERNAME=user-zone-residential
BRIGHTDATA_PASSWORD=your_password
BRIGHTDATA_ZONE=residential  # or datacenter, mobile
```

### 7. Smartproxy
**Residential and datacenter proxies** - https://smartproxy.com/

```bash
PROXY_PROVIDER=smartproxy
SMARTPROXY_URL=http://proxy.smartproxy.com:10001
SMARTPROXY_USERNAME=user
SMARTPROXY_PASSWORD=password
```


---

## Quick Start

### 1. Check Current Status

```bash
# Via CLI
python -m src.cli.cli_modular proxy status

# Via kubectl
kubectl exec -n production deployment/mizzou-processor -- \
  python -m src.cli.cli_modular proxy status
```

### 2. Switch Proxy Provider

**Option A: Update Kubernetes Deployment (Permanent)**

```bash
# Switch to direct (no proxy)
kubectl set env deployment/mizzou-processor -n production PROXY_PROVIDER=direct

# Switch to BrightData
kubectl set env deployment/mizzou-processor -n production PROXY_PROVIDER=brightdata

# Back to Squid
kubectl set env deployment/mizzou-processor -n production PROXY_PROVIDER=squid
```

**Option B: Runtime Switch (Current Process Only)**

```bash
kubectl exec -n production deployment/mizzou-processor -- \
  python -m src.cli.cli_modular proxy switch direct
```

### 3. Test Proxy Configuration

```bash
# Test current provider
python -m src.cli.cli_modular proxy test

# Test with custom URL
python -m src.cli.cli_modular proxy test --url https://example.com
```

### 4. List Available Providers

```bash
python -m src.cli.cli_modular proxy list
```

---

## Usage Scenarios

### Scenario 1: Test Without Proxy

**Problem:** Want to test if bot blocking is proxy-specific

```bash
# Temporarily disable proxy
kubectl set env deployment/mizzou-processor -n production PROXY_PROVIDER=direct

# Wait for rollout
kubectl rollout status deployment/mizzou-processor -n production

# Check extraction success rate
kubectl logs -n production -l app=mizzou-processor --tail=100 | grep "extraction"
```

### Scenario 2: Switch to Different Proxy Service

**Problem:** Current proxy (proxy.kiesow.net) may be blocked

```bash
# Configure BrightData credentials (one-time)
kubectl create secret generic brightdata-credentials -n production \
  --from-literal=url=http://brd.superproxy.io:22225 \
  --from-literal=username=brd-customer-your_id-zone-residential \
  --from-literal=password=your_password

# Update deployment to use BrightData
kubectl set env deployment/mizzou-processor -n production \
  PROXY_PROVIDER=brightdata \
  BRIGHTDATA_PROXY_URL=http://brd.superproxy.io:22225

# Add credentials from secret
kubectl set env deployment/mizzou-processor -n production \
  --from=secret/brightdata-credentials
```

### Scenario 3: A/B Testing Different Proxies

**Problem:** Want to compare performance of different providers

```bash
# Create two deployments with different proxies
# Deployment A: Origin proxy
kubectl create -f k8s/processor-deployment-origin.yaml

# Deployment B: BrightData proxy
kubectl create -f k8s/processor-deployment-brightdata.yaml

# Monitor success rates from each
kubectl logs -l variant=origin --tail=100 | grep "success rate"
kubectl logs -l variant=brightdata --tail=100 | grep "success rate"
```

### Scenario 4: Emergency Failover

**Problem:** Primary proxy service is down

```bash
# Quick switch to backup provider
kubectl set env deployment/mizzou-processor -n production \
  PROXY_PROVIDER=smartproxy

# Verify switch
kubectl exec -n production deployment/mizzou-processor -- \
  python -m src.cli.cli_modular proxy status
```

---

## CLI Commands

### `proxy status`

Show current proxy configuration and health metrics

```bash
$ python -m src.cli.cli_modular proxy status

🔀 Proxy Status
============================================================

Active Provider: origin

Provider Details:
------------------------------------------------------------
→ origin       [✓]
    URL: http://proxy.kiesow.net:23432
    Health: healthy (95.2%)
    Requests: 1523, Avg time: 1.34s

  direct       [✓]
    URL: N/A
    Health: healthy (100.0%)
    Requests: 0, Avg time: 0.00s

  brightdata   [✓]
    URL: http://brd.superproxy.io:22225
    Health: degraded (75.3%)
    Requests: 234, Avg time: 2.15s
```

### `proxy switch <provider>`

Switch to a different proxy provider

```bash
$ python -m src.cli.cli_modular proxy switch direct

🔄 Switching proxy provider to: direct

✅ Successfully switched to direct

Note: This affects the current process only.
To make this permanent, set PROXY_PROVIDER environment variable:
  export PROXY_PROVIDER=direct

Or update your Kubernetes deployment:
  kubectl set env deployment/mizzou-processor PROXY_PROVIDER=direct
```

### `proxy test [--url URL]`

Test current proxy configuration

```bash
$ python -m src.cli.cli_modular proxy test --url https://www.nytimes.com

🧪 Testing proxy with URL: https://www.nytimes.com

Active Provider: origin
Proxy URL: http://proxy.kiesow.net:23432

Testing with ContentExtractor...
------------------------------------------------------------
✅ Request successful (1.23s)

Response details:
  Title: The New York Times - Breaking News, US News, World Ne...
  Status: success
```

### `proxy list`

List all configured proxy providers

```bash
$ python -m src.cli.cli_modular proxy list

📋 Configured Proxy Providers
============================================================

[✓] brightdata
    Provider: BRIGHTDATA
    Enabled: True
    URL: http://brd.superproxy.io:22225
    Username: brd-customer-xyz
    Password: ********

[✓] direct
    Provider: DIRECT
    Enabled: True
    URL: N/A

[✓] origin
    Provider: ORIGIN
    Enabled: True
    URL: http://proxy.kiesow.net:23432
    Username: your_user
    Password: ********
```

---

## Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────┐
│ ContentExtractor / Crawler                          │
│ ┌─────────────────────────────────────────────────┐ │
│ │ ProxyManager (src/crawler/proxy_config.py)     │ │
│ │ - Reads PROXY_PROVIDER env var                 │ │
│ │ - Loads all provider configurations            │ │
│ │ - Returns active config                        │ │
│ └─────────────────────────────────────────────────┘ │
│                        │                             │
│        ┌───────────────┴───────────────┐             │
│        ▼                               ▼             │
│  Squid Proxy                   Standard Proxy      │
│  (requests proxies)            (requests proxies)  │
└─────────────────────────────────────────────────────┘
```

### Files Modified/Created

**New Files:**
- `src/crawler/proxy_config.py` - Proxy configuration manager
- `src/cli/commands/proxy.py` - CLI commands for proxy management
- `docs/PROXY_CONFIGURATION.md` - This documentation

**Integration Points:**
- `src/crawler/__init__.py` - ContentExtractor uses ProxyManager
- `src/cli/cli_modular.py` - Registers proxy commands
- `k8s/processor-deployment.yaml` - Env vars for providers

---

## Environment Variables Reference

### Master Switch

| Variable | Values | Description |
|----------|--------|-------------|
| `PROXY_PROVIDER` | squid, direct, standard, socks5, scraper_api, brightdata, smartproxy | Active proxy provider |

### Squid Proxy (Current Default)

| Variable | Example | Description |
|----------|---------|-------------|
| `SQUID_PROXY_URL` | `http://squid.proxy.net:3128` | Proxy server URL |
| `SQUID_PROXY_USERNAME` | `user` | Authentication username (optional) |
| `SQUID_PROXY_PASSWORD` | `pass` | Authentication password (optional) |

### Standard HTTP Proxy

| Variable | Example | Description |
|----------|---------|-------------|
| `STANDARD_PROXY_URL` | `http://proxy.example.com:8080` | Proxy server URL |
| `STANDARD_PROXY_USERNAME` | `user` | Authentication username |
| `STANDARD_PROXY_PASSWORD` | `pass` | Authentication password |

### SOCKS5 Proxy

| Variable | Example | Description |
|----------|---------|-------------|
| `SOCKS5_PROXY_URL` | `socks5://proxy.example.com:1080` | SOCKS5 server URL |
| `SOCKS5_PROXY_USERNAME` | `user` | Authentication username |
| `SOCKS5_PROXY_PASSWORD` | `pass` | Authentication password |

### ScraperAPI

| Variable | Example | Description |
|----------|---------|-------------|
| `SCRAPERAPI_KEY` | `abc123...` | API key from ScraperAPI |
| `SCRAPERAPI_RENDER` | `false` | Enable JavaScript rendering |
| `SCRAPERAPI_COUNTRY` | `us` | Target country code |

### BrightData

| Variable | Example | Description |
|----------|---------|-------------|
| `BRIGHTDATA_PROXY_URL` | `http://brd.superproxy.io:22225` | BrightData proxy URL |
| `BRIGHTDATA_USERNAME` | `brd-customer-xyz-zone-residential` | Username with zone |
| `BRIGHTDATA_PASSWORD` | `pass` | Account password |
| `BRIGHTDATA_ZONE` | `residential` | Proxy zone (residential/datacenter/mobile) |

### Smartproxy

| Variable | Example | Description |
|----------|---------|-------------|
| `SMARTPROXY_URL` | `http://gate.smartproxy.com:7000` | Smartproxy endpoint |
| `SMARTPROXY_USERNAME` | `user` | Account username |
| `SMARTPROXY_PASSWORD` | `pass` | Account password |

---

## Kubernetes Deployment

### Example: Add BrightData as Secondary Provider

**1. Create Secret (One-Time)**

```yaml
# brightdata-secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: brightdata-credentials
  namespace: production
type: Opaque
stringData:
  url: "http://brd.superproxy.io:22225"
  username: "brd-customer-your_id-zone-residential"
  password: "your_password"
  zone: "residential"
```

```bash
kubectl apply -f brightdata-secret.yaml
```

**2. Update Deployment**

Add to `k8s/processor-deployment.yaml`:

```yaml
env:
  # Existing vars...
  - name: PROXY_PROVIDER
    value: "origin"  # or "brightdata" to make it active

  # BrightData configuration
  - name: BRIGHTDATA_PROXY_URL
    valueFrom:
      secretKeyRef:
        name: brightdata-credentials
        key: url
  - name: BRIGHTDATA_USERNAME
    valueFrom:
      secretKeyRef:
        name: brightdata-credentials
        key: username
  - name: BRIGHTDATA_PASSWORD
    valueFrom:
      secretKeyRef:
        name: brightdata-credentials
        key: password
  - name: BRIGHTDATA_ZONE
    valueFrom:
      secretKeyRef:
        name: brightdata-credentials
        key: zone
```

**3. Deploy**

```bash
kubectl apply -f k8s/processor-deployment.yaml
```

**4. Switch When Needed**

```bash
# Switch to BrightData
kubectl set env deployment/mizzou-processor -n production PROXY_PROVIDER=brightdata

# Switch back to Squid
kubectl set env deployment/mizzou-processor -n production PROXY_PROVIDER=squid
```

---

## Cost Comparison

| Provider | Type | Pricing | Best For |
|----------|------|---------|----------|
| **Origin (Current)** | Private | ~$2-6/month | Current setup, low volume |
| **Direct** | None | Free | Testing, non-blocked sites |
| **ScraperAPI** | API | $49-249/month | Easy integration, JS rendering |
| **BrightData** | Residential | $500+/month | High success rate, premium IPs |
| **Smartproxy** | Residential | $75-1000/month | Good balance of cost/performance |
| **Standard Proxy** | Various | $5-100/month | Budget option |

---

## Monitoring & Telemetry

The proxy system automatically tracks:

- **Success Rate** - Percentage of successful requests
- **Response Time** - Average response time per provider
- **Request Count** - Total requests through each provider
- **Health Status** - healthy/degraded/unhealthy/critical

View metrics with:

```bash
kubectl exec -n production deployment/mizzou-processor -- \
  python -m src.cli.cli_modular proxy status
```

---

## Troubleshooting

### Issue: "Provider not configured"

**Cause:** Environment variables not set for that provider

**Solution:**
```bash
# Check what's configured
python -m src.cli.cli_modular proxy list

# Add missing provider (example for BrightData)
kubectl set env deployment/mizzou-processor -n production \
  BRIGHTDATA_PROXY_URL=http://brd.superproxy.io:22225 \
  BRIGHTDATA_USERNAME=your_user \
  BRIGHTDATA_PASSWORD=your_pass
```

### Issue: "Switch successful but still using old proxy"

**Cause:** Runtime switch only affects current process

**Solution:** Update deployment env var for permanent change
```bash
kubectl set env deployment/mizzou-processor -n production PROXY_PROVIDER=desired_provider
kubectl rollout restart deployment/mizzou-processor -n production
```

### Issue: "Proxy test fails"

**Cause:** Invalid credentials or blocked IP

**Solution:**
1. Check credentials: `kubectl get secret <secret-name> -o yaml`
2. Test proxy directly: `curl -x http://user:pass@proxy:port https://httpbin.org/ip`
3. Check provider dashboard for IP restrictions

---

## Next Steps

1. ✅ **Implemented** - Multi-proxy configuration system
2. ⏳ **Test** - Try `PROXY_PROVIDER=direct` to test without proxy
3. ⏳ **Evaluate** - If bot blocking persists, try BrightData or ScraperAPI
4. ⏳ **Monitor** - Track success rates with `proxy status` command
5. ⏳ **Optimize** - Switch to best-performing provider based on metrics

---

## Support

**Documentation:** This file
**CLI Help:** `python -m src.cli.cli_modular proxy --help`
**Code:** `src/crawler/proxy_config.py`, `src/cli/commands/proxy.py`
