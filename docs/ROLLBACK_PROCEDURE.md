# Emergency Rollback Procedure for GKE Deployments

## Quick Rollback Commands

If a deployment causes issues, use these commands to immediately roll back:

### Roll Back API Deployment
```bash
kubectl rollout undo deployment/mizzou-api -n production
kubectl rollout status deployment/mizzou-api -n production
```

### Roll Back Processor Deployment
```bash
kubectl rollout undo deployment/mizzou-processor -n production
kubectl rollout status deployment/mizzou-processor -n production
```

### Roll Back Crawler Deployment  
```bash
kubectl rollout undo deployment/mizzou-crawler -n production
kubectl rollout status deployment/mizzou-crawler -n production
```

## Verify Rollback Success

After rollback, check:

1. **Pods are running**:
   ```bash
   kubectl get pods -n production
   ```

2. **Check logs for errors**:
   ```bash
   kubectl logs -n production -l app=mizzou-api --tail=50
   kubectl logs -n production -l app=mizzou-processor --tail=50
   ```

3. **Verify health**:
   ```bash
   # API health check
   kubectl port-forward -n production svc/mizzou-api 8080:80 &
   curl http://localhost:8080/health
   ```

## Manual Image Rollback (if needed)

If `kubectl rollout undo` doesn't work, manually set to previous image:

### Find Previous Image Tags
```bash
gcloud artifacts docker tags list \
  us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/api \
  --format="table(tag,IMAGE,CREATE_TIME)" \
  --limit=10
```

### Set Specific Image
```bash
# Replace <previous-sha> with the working commit SHA
kubectl set image deployment/mizzou-api -n production \
  api=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/api:<previous-sha>
  
kubectl set image deployment/mizzou-processor -n production \
  processor=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:<previous-sha>
```

## Known Good Images (as of October 5, 2025)

**Current Working Versions**:
- API: `39b1f08` (telemetry Cloud SQL migration)
- Processor: `39b1f08` (orchestration fix without --limit 50 bug)
- Crawler: (no recent changes)

**Previous Stable (if 39b1f08 fails)**:
```bash
kubectl get deployment mizzou-api -n production -o jsonpath='{.spec.template.spec.containers[0].image}'
kubectl get deployment mizzou-processor -n production -o jsonpath='{.spec.template.spec.containers[0].image}'
```

## Post-Rollback Actions

1. **Stop any ongoing builds**:
   ```bash
   gcloud builds list --ongoing
   # Cancel any problematic builds
   gcloud builds cancel <BUILD_ID>
   ```

2. **Investigate failure**:
   - Check build logs: `gcloud builds log <BUILD_ID>`
   - Check pod events: `kubectl describe pod <POD_NAME> -n production`
   - Check application logs: `kubectl logs <POD_NAME> -n production --previous`

3. **Update team**: Post in Slack/GitHub issue with:
   - What was deployed
   - What went wrong  
   - Current state (rolled back to X)
   - Next steps

## Prevention Checklist (before next deployment)

- [ ] All tests passed locally
- [ ] Docker images build successfully in Cloud Build
- [ ] Health checks return 200 OK
- [ ] No import/module errors in logs
- [ ] Database migrations (if any) are reversible
- [ ] Rollback procedure documented and ready
- [ ] Team member on standby during deployment window

## Emergency Contacts

- **GCP Console**: https://console.cloud.google.com/kubernetes/workload?project=mizzou-news-crawler
- **Cloud Build**: https://console.cloud.google.com/cloud-build/builds?project=mizzou-news-crawler
- **Cloud Deploy**: https://console.cloud.google.com/deploy/delivery-pipelines?project=mizzou-news-crawler

---

**Last Updated**: October 5, 2025  
**Maintained By**: DevOps Team
