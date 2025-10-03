# Phase 2.5 Complete: GKE Cluster Created

**Status**: ✅ **COMPLETE**  
**Date**: October 3, 2025  
**Duration**: ~10 minutes

## Summary

Successfully created Google Kubernetes Engine (GKE) cluster with autoscaling, workload identity, and production namespace. Cluster is ready for application deployment.

## Cluster Configuration

### Cluster Details

- **Cluster Name**: `mizzou-cluster`
- **Status**: RUNNING ✅
- **Location**: us-central1-a (zonal)
- **Kubernetes Version**: v1.33.4-gke.1172000
- **Control Plane Endpoint**: 136.114.158.57
- **Project**: mizzou-news-crawler

### Node Configuration

- **Machine Type**: e2-small
- **vCPUs per node**: 2
- **Memory per node**: 2GB RAM
- **Disk per node**: 30GB standard persistent disk
- **Current nodes**: 1
- **Autoscaling**: Enabled (min: 1, max: 3)

### Network Configuration

- **Network**: default VPC
- **Subnetwork**: default
- **IP Allocation**: VPC-native (alias IPs enabled)
- **Pod CIDR**: Auto-assigned
- **Service CIDR**: Auto-assigned

### Features Enabled

✅ **Workload Identity**: `mizzou-news-crawler.svc.id.goog`
✅ **Cloud Logging**: Enabled (legacy Stackdriver Kubernetes)
✅ **Cloud Monitoring**: Enabled  
✅ **Horizontal Pod Autoscaling**: Enabled
✅ **HTTP Load Balancing**: Enabled (Ingress controller)
✅ **GCE Persistent Disk CSI Driver**: Enabled

### Features Disabled (Development Mode)

- ❌ **Auto-upgrade**: Disabled (manual control)
- ❌ **Auto-repair**: Disabled (manual control)
- ❌ **Binary Authorization**: Not configured
- ❌ **Private Cluster**: Not configured (public endpoint)

## Cost Estimate

### Base Cluster

- **GKE Management**: FREE (Google doesn't charge for GKE cluster management)
- **1 e2-small node**: ~$30/month
- **Autoscaling to 3 nodes**: ~$90/month maximum
- **Persistent disk (30GB standard)**: ~$1.20/month per node

### Total Estimated Monthly Cost

- **Minimum (1 node)**: ~$31/month
- **Average (2 nodes)**: ~$62/month  
- **Maximum (3 nodes)**: ~$93/month

*Note: Actual costs vary based on:*
- Network egress
- Load balancer usage
- Persistent volume claims
- Actual CPU/memory usage

## Kubernetes Access

### kubectl Configuration

kubectl is configured and connected to the cluster:

```bash
# Cluster context
gke_mizzou-news-crawler_us-central1-a_mizzou-cluster

# Default namespace
production
```

### Verify Access

```bash
# Check cluster info
kubectl cluster-info

# List nodes
kubectl get nodes

# List namespaces
kubectl get namespaces

# Check current context
kubectl config current-context
```

### Re-authenticate (if needed)

```bash
# Get fresh credentials
gcloud container clusters get-credentials mizzou-cluster \
  --zone=us-central1-a \
  --project=mizzou-news-crawler

# Or set in one command
source ~/.mizzou-gcp-env && \
gcloud container clusters get-credentials $CLUSTER_NAME --zone=$ZONE
```

## Namespaces

### Production Namespace

- **Name**: `production`
- **Status**: Active
- **Default**: Yes (all kubectl commands use this namespace by default)
- **Purpose**: Application deployment (API, Crawler, Processor)

### System Namespaces

- `default`: Kubernetes default namespace
- `kube-system`: Kubernetes system components
- `kube-public`: Publicly accessible cluster info
- `kube-node-lease`: Node heartbeat/lease management
- `gke-managed-*`: GKE-managed system namespaces
- `gmp-*`: Google Managed Prometheus

## Workload Identity

Workload Identity is enabled, allowing pods to access Google Cloud services securely without service account keys.

### Workload Pool

- **Pool**: `mizzou-news-crawler.svc.id.goog`
- **Purpose**: Allows Kubernetes ServiceAccounts to impersonate GCP Service Accounts
- **Use Case**: Access Secret Manager, Cloud SQL, etc. from pods

### Setup (will be done in Phase 2.6)

1. Create GCP Service Account
2. Grant IAM permissions (Secret Manager, Cloud SQL)
3. Bind Kubernetes ServiceAccount to GCP ServiceAccount
4. Annotate pods to use ServiceAccount

## Cluster Nodes

### Current Nodes

```
NAME                                            STATUS   ROLES    AGE     VERSION
gke-mizzou-cluster-default-pool-2ae6c45e-fdsg   Ready    <none>   10m     v1.33.4-gke.1172000
```

### Node Specifications

- **OS Image**: Container-Optimized OS
- **Architecture**: ARM64 (Apple Silicon compatible)
- **Container Runtime**: containerd
- **kubelet**: v1.33.4-gke.1172000
- **kube-proxy**: v1.33.4-gke.1172000

### Autoscaling Behavior

The cluster will automatically:
- **Scale up** when pods are pending due to insufficient resources
- **Scale down** when nodes are underutilized for 10+ minutes
- Maintain minimum 1 node, maximum 3 nodes
- Respect PodDisruptionBudgets during scaling

## Add-ons and Controllers

### HTTP Load Balancing (Ingress)

- **Status**: Enabled
- **Purpose**: Create external load balancers for Ingress resources
- **Usage**: Will be used in Phase 2.7 for domain/SSL setup

### Horizontal Pod Autoscaler (HPA)

- **Status**: Enabled
- **Purpose**: Automatically scale pods based on CPU/memory
- **Metrics Server**: Running in kube-system namespace

### GCE Persistent Disk CSI Driver

- **Status**: Enabled
- **Purpose**: Dynamic provisioning of persistent volumes
- **Default StorageClass**: standard (HDD-based persistent disks)

## Monitoring and Logging

### Cloud Logging

All cluster logs are sent to Cloud Logging:

- Container logs
- Node logs  
- Cluster audit logs
- GKE system logs

View logs: https://console.cloud.google.com/logs/query?project=mizzou-news-crawler

### Cloud Monitoring

Cluster metrics available in Cloud Monitoring:

- CPU/memory usage
- Network traffic
- Disk I/O
- Pod/container metrics

View monitoring: https://console.cloud.google.com/monitoring/dashboards?project=mizzou-news-crawler

## Security

### Current Security Posture

✅ **Implemented**:
- Workload Identity enabled
- Latest Kubernetes version (1.33.4)
- Container-Optimized OS on nodes
- Cloud Logging/Monitoring enabled

⚠️ **Not Yet Implemented** (consider for production hardening):
- Private GKE cluster (nodes not exposed to internet)
- Binary Authorization (image signing/verification)
- Pod Security Standards/Policies
- Network Policies
- VPC Service Controls
- Shielded GKE nodes

### IAM and RBAC

- **Cluster Admin**: chair@localnewsimpact.org (via gcloud auth)
- **Default Compute ServiceAccount**: Used by nodes
- **Kubernetes RBAC**: Default roles active

## Next Steps: Phase 2.6 - Kubernetes Deployment

Now that GKE cluster is ready, proceed to Phase 2.6 to deploy the application:

### 2.6.1: Create Kubernetes Resources

1. **Create Kubernetes Secrets** from GCP Secret Manager:
   - db-password
   - db-connection-string
   - db-instance-connection-name

2. **Create GCP Service Account** for Workload Identity:
   - Grant Secret Manager accessor role
   - Grant Cloud SQL client role

3. **Create Kubernetes ServiceAccount**:
   - Annotate with GCP service account binding

### 2.6.2: Deploy API Service

1. **Create Deployment** for API:
   - Use `api:latest` image from Artifact Registry
   - Add Cloud SQL Proxy sidecar container
   - Mount secrets as environment variables
   - Configure resource requests/limits
   - Add liveness/readiness probes

2. **Create Service** (ClusterIP):
   - Expose API on port 8000
   - Internal load balancing

### 2.6.3: Deploy Crawler and Processor

1. **Create CronJob** for Crawler:
   - Schedule: TBD (hourly? daily?)
   - Use `crawler:latest` image
   - Share database connection with API

2. **Create CronJob** for Processor:
   - Schedule: TBD (every 6 hours? daily?)
   - Use `processor:latest` image
   - Share database connection with API

### 2.6.4: Test Deployments

1. Verify pods are running
2. Check logs for errors
3. Test database connectivity
4. Verify Secret Manager access

See `docs/PHASE_2_IMPLEMENTATION.md` for detailed deployment manifests.

## Troubleshooting

### Cannot connect to cluster

```bash
# Re-authenticate
gcloud container clusters get-credentials mizzou-cluster \
  --zone=us-central1-a \
  --project=mizzou-news-crawler
```

### kubectl command not found

```bash
# Install kubectl
brew install kubectl

# Or via gcloud
gcloud components install kubectl
```

### Nodes not ready

```bash
# Check node status
kubectl get nodes -o wide

# Describe node for details
kubectl describe node <node-name>

# Check events
kubectl get events --all-namespaces
```

### Pods stuck in Pending

```bash
# Check pod status
kubectl get pods -n production

# Describe pod for events
kubectl describe pod <pod-name> -n production

# Check cluster has available resources
kubectl top nodes
```

## Useful Commands

```bash
# Get cluster details
gcloud container clusters describe mizzou-cluster --zone=us-central1-a

# List all resources in production namespace
kubectl get all -n production

# Watch pod status
kubectl get pods -n production --watch

# Get pod logs
kubectl logs <pod-name> -n production

# Execute command in pod
kubectl exec -it <pod-name> -n production -- /bin/bash

# Port forward to pod
kubectl port-forward <pod-name> 8000:8000 -n production

# Scale deployment
kubectl scale deployment <deployment-name> --replicas=2 -n production

# Delete all resources in namespace
kubectl delete all --all -n production
```

## Environment Variables

Update `~/.mizzou-gcp-env` with cluster details:

```bash
# Add these to ~/.mizzou-gcp-env
export CLUSTER_NAME="mizzou-cluster"
export CLUSTER_ZONE="us-central1-a"
export CLUSTER_ENDPOINT="136.114.158.57"
export K8S_NAMESPACE="production"
```

## Phase 2 Progress

- ✅ Phase 2.1: Prerequisites Installation (gcloud CLI, kubectl)
- ✅ Phase 2.2: GCP Project Setup (project created, billing linked, APIs enabled)
- ✅ Phase 2.3: Artifact Registry & Docker Images (all images pushed)
- ✅ Phase 2.4: Cloud SQL PostgreSQL Setup (database ready)
- ✅ **Phase 2.5: GKE Cluster Creation** ← **YOU ARE HERE**
- ⏳ Phase 2.6: Kubernetes Deployment (deploy API, Crawler, Processor)
- ⏳ Phase 2.7: Domain & SSL Configuration (compute.localnewsimpact.org)

---

**Phase 2.5 Status**: ✅ **COMPLETE** - GKE cluster ready for application deployment.
