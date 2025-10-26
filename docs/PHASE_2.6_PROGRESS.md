# Phase 2.6 Progress: Kubernetes Deployment (In Progress)

**Status**: ⚠️ **IN PROGRESS - Architecture Issue Identified**  
**Date**: October 3, 2025

## Summary

Successfully deployed all Kubernetes resources (API, Crawler, Processor) but discovered an architecture mismatch preventing containers from running. All infrastructure and configurations are correct - only need to rebuild Docker images for AMD64.

## ✅ Completed Steps

### 1. GCP Service Account & IAM

- ✅ Created GCP service account: `mizzou-k8s-sa@mizzou-news-crawler.iam.gserviceaccount.com`
- ✅ Granted `roles/secretmanager.secretAccessor` for Secret Manager access
- ✅ Granted `roles/cloudsql.client` for Cloud SQL access
- ✅ Granted `roles/artifactregistry.reader` to compute nodes for image pulling

### 2. Workload Identity Setup

- ✅ Created Kubernetes ServiceAccount: `mizzou-app` in `production` namespace
- ✅ Annotated with GCP service account for Workload Identity
- ✅ Bound Kubernetes SA to GCP SA with `roles/iam.workloadIdentityUser`
- ✅ Binding: `mizzou-news-crawler.svc.id.goog[production/mizzou-app]`

### 3. Kubernetes Secrets

- ✅ Created secret: `cloudsql-db-credentials`
- ✅ Contains: username, password, database name, instance connection name
- ✅ Fetched from GCP Secret Manager

### 4. API Deployment

- ✅ Created Deployment manifest: `k8s/api-deployment.yaml`
- ✅ API container configured with DATABASE_URL
- ✅ Cloud SQL Proxy sidecar configured
- ✅ LoadBalancer Service created
- ✅ External IP provisioned: **104.154.178.89**
- ✅ Health check probes configured (liveness & readiness)
- ✅ Resource limits adjusted for e2-small nodes

### 5. Crawler CronJob

- ✅ Created CronJob manifest: `k8s/crawler-cronjob.yaml`
- ✅ Schedule: Daily at 2 AM UTC (`0 2 * * *`)
- ✅ Cloud SQL Proxy sidecar configured
- ✅ Database credentials from Kubernetes secrets
- ✅ Deployed to cluster

### 6. Processor CronJob

- ✅ Created CronJob manifest: `k8s/processor-cronjob.yaml`
- ✅ Schedule: Every 6 hours (`0 */6 * * *`)
- ✅ Cloud SQL Proxy sidecar configured
- ✅ Database credentials from Kubernetes secrets
- ✅ Deployed to cluster

### 7. Cluster Auto-scaling

- ✅ Cluster successfully auto-scaled from 1 to 2 nodes
- ✅ Demonstrated autoscaling works correctly
- ✅ Resource requests optimized for e2-small nodes

## ⚠️ Current Issue: Architecture Mismatch

### Problem

Docker images were built on **Apple Silicon (ARM64)** but GKE nodes are **AMD64 (x86_64)**:

```
Error: exec /usr/local/bin/uvicorn: exec format error
```

### Verification

```bash
# Node architecture
$ kubectl get nodes -o jsonpath='{.items[0].status.nodeInfo.architecture}'
amd64

# Images built on ARM64 (Apple Silicon Mac)
```

### Solution Required

Rebuild Docker images for AMD64 architecture using one of these methods:

#### Option 1: Build on AMD64 Machine (Simplest)

Build images on an x86_64 machine or Linux VM.

#### Option 2: Multi-Platform Build with Docker Buildx (Recommended)

```bash
# Enable Docker buildx
docker buildx create --name multiplatform --use
docker buildx inspect --bootstrap

# Build for AMD64
docker buildx build --platform linux/amd64 \
  -t us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/api:v1.0.1 \
  -f Dockerfile.api \
  --push .

docker buildx build --platform linux/amd64 \
  -t us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/crawler:v1.0.1 \
  -f Dockerfile.crawler \
  --push .

docker buildx build --platform linux/amd64 \
  -t us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:v1.0.1 \
  -f Dockerfile.processor \
  --push .
```

#### Option 3: Multi-Architecture Images (Production-Ready)

```bash
# Build for both ARM64 and AMD64
docker buildx build --platform linux/amd64,linux/arm64 \
  -t us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/api:latest \
  -t us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/api:v1.0.1 \
  -f Dockerfile.api \
  --push .
```

### Update Deployment

After rebuilding, either:

1. Update image tag in manifests to `v1.0.1` if using versioned tags
2. Delete pods to force pull new `:latest` images:

```bash
kubectl delete pod -n production -l app=mizzou-api
```

## Current Kubernetes State

### Nodes

```
NAME                                            STATUS   ROLES    AGE   VERSION
gke-mizzou-cluster-default-pool-2ae6c45e-fdsg   Ready    <none>   15m   v1.33.4-gke.1172000
gke-mizzou-cluster-default-pool-2ae6c45e-twq7   Ready    <none>   10m   v1.33.4-gke.1172000
```

- 2 nodes active (auto-scaled)
- Architecture: AMD64
- Machine type: e2-small

### Deployments

```
NAME         READY   UP-TO-DATE   AVAILABLE   AGE
mizzou-api   0/1     1            0           5m
```

### Services

```
NAME         TYPE           CLUSTER-IP       EXTERNAL-IP      PORT(S)        AGE
mizzou-api   LoadBalancer   34.118.225.121   104.154.178.89   80:30516/TCP   5m
```

### CronJobs

```
NAME               SCHEDULE      SUSPEND   ACTIVE   LAST SCHEDULE   AGE
mizzou-crawler     0 2 * * *     False     0        <none>          3m
mizzou-processor   0 */6 * * *   False     0        <none>          3m
```

### Pods

```
NAME                          READY   STATUS             RESTARTS   AGE
mizzou-api-79754b8944-btc5t   1/2     CrashLoopBackOff   2          2m
```

- Cloud SQL Proxy container: Running ✅
- API container: CrashLoopBackOff (architecture mismatch) ⚠️

## Infrastructure Summary

### What's Working

✅ GKE cluster operational  
✅ Cloud SQL database accessible  
✅ Workload Identity configured  
✅ Secrets management setup  
✅ Load balancer provisioned  
✅ Auto-scaling functional  
✅ All Kubernetes manifests valid  
✅ Network connectivity established  

### What Needs Fixing

⚠️ Docker images need AMD64 architecture rebuild

## Next Steps

1. **Rebuild Docker Images for AMD64**
   - Use Docker buildx with `--platform linux/amd64`
   - Push to Artifact Registry as v1.0.1 or rebuild :latest
   - Estimated time: 15-20 minutes for all 3 images

2. **Update Deployments**
   - Either update image tags in manifests
   - Or delete pods to force new image pull

3. **Verify Deployment**
   - Check pod status: `kubectl get pods -n production`
   - Check API logs: `kubectl logs -n production -l app=mizzou-api -c api`
   - Test external IP: `curl http://104.154.178.89/health`

4. **Test CronJobs**
   - Trigger manual run to test before scheduled execution
   - `kubectl create job --from=cronjob/mizzou-crawler test-crawler -n production`

5. **Complete Documentation**
   - Create Phase 2.6 completion document
   - Document architecture resolution
   - Update environment variables

## Cost Impact

Current running costs:
- 2 × e2-small nodes: ~$62/month
- Cloud SQL db-f1-micro: ~$10/month
- Load Balancer: ~$18/month
- **Total**: ~$90/month

*Note: Will scale down to 1 node (~$31/month) when pods are not running*

## Files Created

- `k8s/api-deployment.yaml` - API Deployment with LoadBalancer Service
- `k8s/crawler-cronjob.yaml` - Crawler CronJob (daily at 2 AM)
- `k8s/processor-cronjob.yaml` - Processor CronJob (every 6 hours)

## Kubernetes Resources

- Namespace: `production`
- ServiceAccount: `mizzou-app` (Workload Identity enabled)
- Secret: `cloudsql-db-credentials`
- Deployment: `mizzou-api`
- Service: `mizzou-api` (LoadBalancer)
- CronJob: `mizzou-crawler`
- CronJob: `mizzou-processor`

## Testing Once Fixed

### Test API

```bash
# Health check
curl http://104.154.178.89/health

# Check logs
kubectl logs -n production -l app=mizzou-api -c api

# Check Cloud SQL Proxy
kubectl logs -n production -l app=mizzou-api -c cloud-sql-proxy
```

### Test CronJobs

```bash
# Manual crawler run
kubectl create job --from=cronjob/mizzou-crawler test-crawler -n production

# Watch job
kubectl get jobs -n production --watch

# Check logs
kubectl logs -n production job/test-crawler -c crawler
```

## Phase 2 Progress

- ✅ Phase 2.1: Prerequisites Installation
- ✅ Phase 2.2: GCP Project Setup
- ✅ Phase 2.3: Artifact Registry & Docker Images
- ✅ Phase 2.4: Cloud SQL PostgreSQL Setup
- ✅ Phase 2.5: GKE Cluster Creation
- ⚠️ **Phase 2.6: Kubernetes Deployment** ← **IN PROGRESS** (architecture fix needed)
- ⏳ Phase 2.7: Domain & SSL Configuration

---

**Status**: Ready to proceed once Docker images are rebuilt for AMD64 architecture. All other infrastructure and configurations are complete and working correctly.
