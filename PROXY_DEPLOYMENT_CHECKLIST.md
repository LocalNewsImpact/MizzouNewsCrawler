# Proxy Deployment Checklist

Use this checklist when deploying the proxy configuration to a Kubernetes cluster.

## Pre-Deployment

- [ ] Review [docs/PROXY_DEPLOYMENT_GUIDE.md](docs/PROXY_DEPLOYMENT_GUIDE.md)
- [ ] Obtain proxy credentials (username and password)
- [ ] Verify proxy server is accessible from the cluster
- [ ] Have `kubectl` configured for target cluster
- [ ] Identify correct namespace (typically `production`)
- [ ] Identify target Python version in container (typically 3.12)

## Step 1: Prepare Credentials

- [ ] URL-encode the proxy password:
  ```bash
  python scripts/encode_proxy_password.py "your_password"
  ```
- [ ] Note the encoded password for SELENIUM_PROXY

## Step 2: Create Secret

- [ ] Create the secret with actual credentials:
  ```bash
  kubectl create secret generic origin-proxy-credentials \
    --namespace=production \
    --from-literal=PROXY_USERNAME='news_crawler' \
    --from-literal=PROXY_PASSWORD='your_password' \
    --from-literal=ORIGIN_PROXY_URL='http://proxy.kiesow.net:23432' \
    --from-literal=SELENIUM_PROXY='http://news_crawler:encoded_password@proxy.kiesow.net:23432'
  ```

- [ ] Verify secret was created:
  ```bash
  kubectl get secret origin-proxy-credentials -n production
  ```

- [ ] Check secret has all required keys:
  ```bash
  kubectl get secret origin-proxy-credentials -n production -o yaml
  ```

## Step 3: Deploy ConfigMap

- [ ] Apply the ConfigMap:
  ```bash
  kubectl apply -f k8s/origin-sitecustomize-configmap.yaml
  ```

- [ ] Verify ConfigMap was created:
  ```bash
  kubectl get configmap origin-sitecustomize -n production
  ```

- [ ] Check ConfigMap contains sitecustomize.py:
  ```bash
  kubectl get configmap origin-sitecustomize -n production -o yaml | grep sitecustomize.py
  ```

## Step 4: Update Deployments

### For Processor

- [ ] Review changes in `k8s/processor-deployment.yaml`
- [ ] Verify the volume mount path matches your Python version
- [ ] Apply the updated deployment:
  ```bash
  kubectl apply -f k8s/processor-deployment.yaml
  ```

### For Crawler CronJob

- [ ] Review changes in `k8s/crawler-cronjob.yaml`
- [ ] Verify the volume mount path matches your Python version
- [ ] Apply the updated cronjob:
  ```bash
  kubectl apply -f k8s/crawler-cronjob.yaml
  ```

## Step 5: Verify Mount Path (Important!)

- [ ] Get a running pod:
  ```bash
  POD=$(kubectl get pods -n production -l app=mizzou-processor -o name | head -n1 | sed 's#pod/##')
  echo $POD
  ```

- [ ] Check the actual Python site-packages path:
  ```bash
  kubectl exec -n production $POD -- python -c "import site; print(site.getsitepackages()[0])"
  ```

- [ ] If the path differs from `/usr/local/lib/python3.12/site-packages`:
  - [ ] Update the `mountPath` in deployment YAMLs
  - [ ] Reapply the deployments

## Step 6: Restart Services

- [ ] Restart processor deployment:
  ```bash
  kubectl rollout restart deployment/mizzou-processor -n production
  ```

- [ ] Wait for rollout to complete:
  ```bash
  kubectl rollout status deployment/mizzou-processor -n production
  ```

- [ ] Check new pod is running:
  ```bash
  kubectl get pods -n production -l app=mizzou-processor
  ```

## Step 7: Validation

- [ ] Run the validation script:
  ```bash
  ./scripts/validate_proxy_deployment.sh production mizzou-processor
  ```

- [ ] Check pod logs for shim activation:
  ```bash
  kubectl logs -n production $POD | grep origin-shim
  ```
  Expected: `INFO:origin-shim:origin-shim enabled: routing requests through http://proxy.kiesow.net:23432`

- [ ] Verify sitecustomize.py is mounted:
  ```bash
  kubectl exec -n production $POD -- ls -la /usr/local/lib/python3.12/site-packages/sitecustomize.py
  ```

- [ ] Check environment variables:
  ```bash
  kubectl exec -n production $POD -- printenv | grep -E "PROXY|ORIGIN"
  ```

- [ ] Test a simple HTTP request:
  ```bash
  kubectl exec -n production $POD -- python -c "
  import requests
  print('Testing request...')
  r = requests.get('http://example.com', timeout=10)
  print(f'Status: {r.status_code}')
  print('✓ Request succeeded')
  "
  ```

## Step 8: Monitor Proxy Server

- [ ] SSH to proxy server (if you have access)
- [ ] Tail proxy logs:
  ```bash
  tail -f ~/apps/proxy-port/logs/proxy-port.log
  ```

- [ ] Look for entries showing:
  - Auth-check OK for news_crawler
  - Proxying: http://example.com

## Troubleshooting

If validation fails:

### sitecustomize.py not mounted
- Check the mount path matches your Python version
- Ensure ConfigMap exists and has correct name
- Verify volume and volumeMount are both present in deployment

### Environment variables missing
- Check secret exists and has correct name
- Verify secretRef in deployment matches secret name
- Ensure keys in secret match what's referenced

### Requests not going through proxy
- Check USE_ORIGIN_PROXY=true
- Verify ORIGIN_PROXY_URL is set
- Look for errors in pod logs
- Check proxy server is reachable from pod

### Authentication failures
- Verify PROXY_USERNAME and PROXY_PASSWORD are correct
- Check credentials work with direct curl test
- Ensure no special characters need escaping

## Rollback Procedure

If something goes wrong:

- [ ] Quick disable (no redeploy):
  ```bash
  kubectl set env deployment/mizzou-processor USE_ORIGIN_PROXY=false -n production
  kubectl rollout restart deployment/mizzou-processor -n production
  ```

- [ ] Full rollback (revert to previous version):
  ```bash
  kubectl rollout undo deployment/mizzou-processor -n production
  kubectl rollout status deployment/mizzou-processor -n production
  ```

- [ ] Verify services are working:
  ```bash
  kubectl get pods -n production
  kubectl logs -n production $POD
  ```

## Post-Deployment

- [ ] Monitor application logs for errors
- [ ] Check proxy server logs for request volume
- [ ] Verify crawler/processor functionality
- [ ] Update documentation if any issues were encountered
- [ ] Document actual Python version and site-packages path used
- [ ] Schedule credential rotation (recommended: every 90 days)

## Notes

Record any deviations from the standard procedure:

```
Date: _______________
Namespace: _______________
Deployment: _______________
Python version: _______________
Site-packages path: _______________
Issues encountered: _______________
_______________________________________________
_______________________________________________
```

## Reference

- Full Guide: [docs/PROXY_DEPLOYMENT_GUIDE.md](docs/PROXY_DEPLOYMENT_GUIDE.md)
- Quick Reference: [k8s/PROXY_README.md](k8s/PROXY_README.md)
- Implementation Details: [PROXY_IMPLEMENTATION_SUMMARY.md](PROXY_IMPLEMENTATION_SUMMARY.md)
