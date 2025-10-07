# Proxy Configuration for Kubernetes Deployments

This directory contains the configuration files needed to deploy a global proxy adapter for all HTTP clients in the crawler application.

## Files

- **sitecustomize.py**: Python startup shim that automatically routes all `requests` library calls through an origin-style proxy
- **origin-sitecustomize-configmap.yaml**: Kubernetes ConfigMap containing the sitecustomize.py file
- **origin-proxy-secret.yaml.template**: Template for creating the proxy credentials secret
- **processor-deployment.yaml**: Updated processor deployment with proxy configuration
- **crawler-cronjob.yaml**: Updated crawler cronjob with proxy configuration

## Quick Start

1. **Create the proxy credentials secret** (replace placeholders with actual values):
   ```bash
   kubectl create secret generic origin-proxy-credentials \
     --namespace=production \
     --from-literal=PROXY_USERNAME='news_crawler' \
     --from-literal=PROXY_PASSWORD='YOUR_PASSWORD' \
     --from-literal=ORIGIN_PROXY_URL='http://proxy.kiesow.net:23432' \
     --from-literal=SELENIUM_PROXY='http://news_crawler:URL_ENCODED_PASSWORD@proxy.kiesow.net:23432'
   ```

2. **Deploy the ConfigMap**:
   ```bash
   kubectl apply -f origin-sitecustomize-configmap.yaml
   ```

3. **Apply the updated deployments**:
   ```bash
   kubectl apply -f processor-deployment.yaml
   kubectl apply -f crawler-cronjob.yaml
   ```

4. **Restart the processor to pick up changes**:
   ```bash
   kubectl rollout restart deployment/mizzou-processor -n production
   ```

## How It Works

The sitecustomize.py file is automatically loaded by Python at interpreter startup. When `USE_ORIGIN_PROXY=true`, it:

1. Patches `requests.Session.request` at the class level
2. Rewrites all HTTP/HTTPS URLs to the origin proxy format: `http://proxy?url=<target>`
3. Adds Basic Authorization headers using `PROXY_USERNAME` and `PROXY_PASSWORD`
4. Applies to ALL code that uses `requests`, including:
   - Direct `requests.get()` calls
   - `cloudscraper.create_scraper()` sessions
   - Any library that uses `requests.Session` internally

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `USE_ORIGIN_PROXY` | Set to `true` to enable proxy routing |
| `ORIGIN_PROXY_URL` | Base URL of the origin-style proxy |
| `PROXY_USERNAME` | Username for proxy authentication |
| `PROXY_PASSWORD` | Password for proxy authentication |
| `SELENIUM_PROXY` | Proxy URL with embedded credentials for Chrome |

## Verification

Check if the shim is active in a pod:

```bash
POD=$(kubectl get pods -n production -l app=mizzou-processor -o name | head -n1 | sed 's#pod/##')

# Check if sitecustomize.py is mounted
kubectl exec -n production $POD -- ls -la /usr/local/lib/python3.12/site-packages/sitecustomize.py

# Check environment variables
kubectl exec -n production $POD -- printenv | grep PROXY

# Test a request
kubectl exec -n production $POD -- python -c "import requests; print(requests.get('http://example.com', timeout=10).status_code)"
```

## Troubleshooting

### Site-packages Path Issues

If sitecustomize.py is not being loaded, the mount path may be incorrect. Find the correct path:

```bash
kubectl exec -n production $POD -- python -c "import site; print(site.getsitepackages())"
```

Then update the `mountPath` in the deployment YAML accordingly.

### Disabling the Proxy

To disable without redeploying:

```bash
kubectl set env deployment/mizzou-processor USE_ORIGIN_PROXY=false -n production
kubectl rollout restart deployment/mizzou-processor -n production
```

## Security Notes

- Credentials are stored in Kubernetes Secrets, never in ConfigMaps or code
- All secret keys are marked `optional: true` so deployments work even if the secret doesn't exist
- The sitecustomize shim logs only boolean flags and proxy URLs, never credentials

## Further Documentation

See [PROXY_DEPLOYMENT_GUIDE.md](../docs/PROXY_DEPLOYMENT_GUIDE.md) for complete deployment instructions and troubleshooting.
