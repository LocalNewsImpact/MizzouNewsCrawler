# Workload Resource Management Strategy

## Overview
This document outlines the resource management strategy for the Mizzou News Crawler Kubernetes cluster. The goal is to ensure efficient resource utilization while preventing resource contention between different workload types.

## Workload Classification

### 1. **Service-Critical** (Priority: 10000)
**Description:** User-facing services that must always be available.

**Workloads:**
- `mizzou-api` - REST API for frontend and external integrations

**Resource Profile:**
- CPU Request: 100m (burst to 500m)
- Memory Request: 256Mi (limit 512Mi)
- Replicas: 2 (with PodDisruptionBudget)
- Expected Usage: 50-200m CPU, 128-256Mi memory

**Scheduling:**
- Priority Class: `service-critical`
- Can preempt any lower-priority workload if needed
- Never run during node maintenance windows

---

### 2. **Service-Standard** (Priority: 5000)
**Description:** Always-on services that support core functionality but can tolerate brief interruptions.

**Workloads:**
- `mizzou-processor` deployment - Background processing, webhook handling
- Monitoring/logging services

**Resource Profile:**
- CPU Request: 100m (burst to 750m)
- Memory Request: 512Mi (limit 1Gi)
- Replicas: 1 (with PodDisruptionBudget)
- Expected Usage: 50-300m CPU, 256-768Mi memory

**Scheduling:**
- Priority Class: `service-standard`
- Can preempt batch and scheduled jobs
- Tolerates brief interruptions for upgrades

---

### 3. **Scheduled-High** (Priority: 1000)
**Description:** Critical scheduled jobs that discover and extract content daily.

**Workloads:**
- `mizzou-crawler` CronJob - Daily at 2 AM UTC (URL discovery)
- Dataset extraction CronJobs (if scheduled)

**Resource Profile:**
- CPU Request: 100-250m (burst to 500m)
- Memory Request: 512Mi-1Gi (limit 2Gi)
- Schedule: Daily 2:00 AM UTC
- Expected Duration: 30-60 minutes
- Expected Usage: 100-400m CPU, 512Mi-1.5Gi memory

**Scheduling:**
- Priority Class: `scheduled-high`
- Can preempt batch jobs
- Scheduled during low-traffic windows (2 AM UTC)
- Concurrency: Forbid (never run overlapping instances)

---

### 4. **Scheduled-Standard** (Priority: 500)
**Description:** Regular scheduled maintenance and processing jobs.

**Workloads:**
- `mizzou-processor` CronJob - Every 6 hours (cleaning, analysis)
- Maintenance jobs (DB cleanup, analytics)

**Resource Profile:**
- CPU Request: 100-200m (burst to 500m)
- Memory Request: 512Mi-1Gi (limit 2Gi)
- Schedule: Every 6 hours (0:00, 6:00, 12:00, 18:00 UTC)
- Expected Duration: 15-45 minutes
- Expected Usage: 50-300m CPU, 256-768Mi memory

**Scheduling:**
- Priority Class: `scheduled-standard`
- Can be preempted by high-priority jobs
- Spread across day to avoid conflicts
- Concurrency: Forbid

---

### 5. **Batch-High** (Priority: 100)
**Description:** Important one-time batch jobs (urgent dataset processing, backfills).

**Workloads:**
- Urgent dataset extraction jobs
- Critical backfill operations
- Emergency reprocessing

**Resource Profile:**
- CPU Request: 100m (burst to 500m)
- Memory Request: 768Mi-1Gi (limit 2Gi)
- Expected Duration: 1-4 hours
- Expected Usage: 50-400m CPU, 512Mi-1.5Gi memory

**Scheduling:**
- Priority Class: `batch-high`
- Can be preempted by services and high-priority cron jobs
- Should NOT be scheduled during known cron windows
- Use for urgent/time-sensitive processing only

---

### 6. **Batch-Standard** (Priority: 50, DEFAULT)
**Description:** Standard batch jobs (dataset extraction, processing, experimentation).

**Workloads:**
- Dataset extraction jobs (like Lehigh)
- Dataset cleaning/analysis jobs
- Ad-hoc processing tasks

**Resource Profile:**
- CPU Request: 100m (burst to 500m)
- Memory Request: 512Mi-1Gi (limit 2Gi)
- Expected Duration: 1-6 hours
- Expected Usage: 50-300m CPU, 512Mi-1.5Gi memory

**Scheduling:**
- Priority Class: `batch-standard` (default)
- Lowest priority, can be preempted by anything
- **AVOID scheduling during cron windows:**
  - 1:30-3:00 AM UTC (crawler cron)
  - 5:30-6:30 AM UTC, 11:30-12:30 PM UTC, 5:30-6:30 PM UTC (processor cron)
- Best windows: 8 AM - 4 PM UTC, 8 PM - 12 AM UTC

---

### 7. **Batch-Low** (Priority: 10)
**Description:** Low-priority background tasks that can run whenever resources are available.

**Workloads:**
- Cleanup jobs
- Log rotation
- Archival tasks
- Experimental/testing jobs

**Resource Profile:**
- CPU Request: 50m (burst to 250m)
- Memory Request: 256Mi-512Mi (limit 1Gi)
- Expected Duration: Variable
- Expected Usage: 10-100m CPU, 128-512Mi memory

**Scheduling:**
- Priority Class: `batch-low`
- Lowest priority, runs only when cluster has idle capacity
- Can be preempted at any time
- Use for non-critical background tasks

---

## Resource Request Guidelines

### CPU Requests
- **Request = Minimum guaranteed CPU** (used for scheduling)
- **Limit = Maximum burst CPU** (can use idle capacity)
- Rule of thumb: Request 50-75% of expected average usage

| Workload Type | Request | Limit | Reasoning |
|---------------|---------|-------|-----------|
| API | 100m | 500m | Low steady-state, can burst for traffic spikes |
| Processor | 100m | 750m | Moderate steady-state, can burst for batches |
| Cron Jobs | 100-200m | 500m | Short-lived, need consistent resources |
| Batch Jobs | 100m | 500m | Long-lived, can tolerate throttling |

### Memory Requests
- **Request = Minimum guaranteed memory** (used for scheduling)
- **Limit = Maximum allowed memory** (OOM kill if exceeded)
- Rule of thumb: Request 75-90% of expected average usage

| Workload Type | Request | Limit | Reasoning |
|---------------|---------|-------|-----------|
| API | 256Mi | 512Mi | Lightweight, stateless |
| Processor | 512Mi | 1Gi | ML models, larger batches |
| Cron/Batch | 512Mi-1Gi | 2Gi | Variable workload size |

---

## Scheduling Best Practices

### 1. **Check Cluster Capacity Before Launching Jobs**
```bash
# Check available CPU/memory
kubectl top nodes

# Check pending pods
kubectl get pods -n production --field-selector=status.phase=Pending
```

### 2. **Avoid Cron Job Windows**
**Known Busy Windows:**
- **2:00-3:00 AM UTC** - Crawler (discovery)
- **6:00-6:30 AM UTC** - Processor (cleaning/analysis)
- **12:00-12:30 PM UTC** - Processor (cleaning/analysis)
- **6:00-6:30 PM UTC** - Processor (cleaning/analysis)

**Best Windows for Batch Jobs:**
- **8:00 AM - 4:00 PM UTC** (business hours, API traffic low)
- **8:00 PM - 12:00 AM UTC** (evening, minimal traffic)

### 3. **Right-Size Your Jobs**
```yaml
# Example: Dataset extraction job
resources:
  requests:
    cpu: 100m          # Guaranteed minimum
    memory: 768Mi      # Need for extraction + ML
  limits:
    cpu: 500m          # Can burst if node has capacity
    memory: 2Gi        # Safety margin for large articles
```

### 4. **Use Priority Classes**
```yaml
# Add to job/deployment spec:
spec:
  template:
    spec:
      priorityClassName: batch-standard  # or appropriate class
```

---

## Cluster Capacity Planning

### Current Cluster (2 nodes)
- **Total Capacity:** ~2000m CPU, ~7Gi memory per node
- **Reserved (system):** ~200m CPU, ~1Gi memory per node
- **Available:** ~1800m CPU, ~6Gi memory per node
- **Total Available:** ~3600m CPU, ~12Gi memory

### Current Resource Allocation

| Component | CPU Request | Memory Request | Priority | Count |
|-----------|-------------|----------------|----------|-------|
| API | 100m | 256Mi | service-critical | 2 |
| Processor | 100m | 512Mi | service-standard | 1 |
| CloudSQL Proxy | 25m | 128Mi | system | 2 |
| **Base Usage** | **325m** | **1.25Gi** | - | - |
| **Available** | **3275m** | **10.75Gi** | - | - |

### Resource Headroom for Jobs

**Safe Batch Job Sizing (to avoid scheduling failures):**
- CPU Request: ≤300m (leaves margin for other jobs)
- Memory Request: ≤1.5Gi (leaves margin for other jobs)

**Maximum Single Job:**
- CPU Request: ≤1000m (can evict low-priority pods if needed)
- Memory Request: ≤3Gi (can evict low-priority pods if needed)

---

## Preemption Strategy

When a high-priority pod needs resources:

1. Kubernetes identifies lower-priority pods that can be evicted
2. Sends SIGTERM to those pods (30s graceful shutdown)
3. Reschedules them after high-priority pod completes
4. Low-priority pods may restart multiple times during busy periods

**Workloads Safe from Preemption:**
- `service-critical` (API) - never preempted
- `service-standard` (processor deployment) - only preempted by critical services

**Workloads Subject to Preemption:**
- All batch jobs (`batch-*`)
- All cron jobs (`scheduled-*`)

---

## Troubleshooting

### Pod Stuck in Pending (Insufficient CPU)

**Cause:** Not enough CPU capacity on any node.

**Solutions:**
1. Reduce CPU request in job spec
2. Wait for other jobs to complete
3. Delete/preempt lower-priority pods
4. Scale cluster up (add nodes)

```bash
# Check what's using CPU
kubectl top pods -n production

# Check pending pods
kubectl get pods -n production --field-selector=status.phase=Pending

# Check node capacity
kubectl describe nodes | grep -A 5 "Allocated resources"
```

### Frequent Preemptions

**Cause:** Cluster is over-subscribed, high-priority jobs keep evicting batch jobs.

**Solutions:**
1. Increase cluster size (autoscaling or manual)
2. Schedule batch jobs during off-peak hours
3. Use lower CPU requests for batch jobs
4. Reduce concurrency (fewer simultaneous jobs)

### OOM Kills (Out of Memory)

**Cause:** Pod exceeded memory limit.

**Solutions:**
1. Increase memory limit
2. Reduce batch size (--limit parameter)
3. Add memory request/limit if missing

```bash
# Check OOM kills
kubectl get pods -n production | grep OOMKilled
kubectl describe pod <pod-name> -n production
```

---

## Future Improvements

### 1. **Cluster Autoscaling** (Recommended)
Enable GKE autoscaling to automatically add nodes when resource requests exceed capacity:

```bash
gcloud container clusters update mizzou-crawler-cluster \
  --enable-autoscaling \
  --min-nodes 2 \
  --max-nodes 5 \
  --zone us-central1-a
```

### 2. **Node Pools for Workload Isolation**
Create separate node pools for services vs. batch workloads:

- **Service Pool:** Always-on, 2 nodes, no autoscaling
- **Batch Pool:** Autoscaling 0-3 nodes, preemptible/spot instances

### 3. **Horizontal Pod Autoscaling**
Auto-scale API/processor based on CPU/memory usage or custom metrics.

### 4. **Resource Quotas**
Limit total resources per namespace to prevent runaway jobs:

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: batch-jobs-quota
  namespace: production
spec:
  hard:
    requests.cpu: "2000m"
    requests.memory: "4Gi"
    limits.cpu: "4000m"
    limits.memory: "8Gi"
```

### 5. **Vertical Pod Autoscaling**
Automatically adjust resource requests based on actual usage patterns.

---

## Quick Reference

### Applying Priority Classes
```bash
# Deploy priority classes
kubectl apply -f k8s/priority-classes.yaml

# Verify
kubectl get priorityclasses
```

### Checking Resource Usage
```bash
# Node capacity
kubectl top nodes

# Pod usage
kubectl top pods -n production

# Available capacity
kubectl describe nodes | grep -A 5 "Allocated resources"
```

### Launching Jobs Safely
```bash
# Check capacity first
kubectl top nodes

# Use appropriate priority class
# Edit job YAML to add:
spec:
  template:
    spec:
      priorityClassName: batch-standard

# Launch job
kubectl apply -f k8s/my-job.yaml
```

---

## Summary

**Key Principles:**
1. ✅ **Always set resource requests** (enables proper scheduling)
2. ✅ **Use priority classes** (ensures critical workloads run)
3. ✅ **Right-size requests** (request 50-75% of expected usage)
4. ✅ **Avoid cron windows** (prevents conflicts)
5. ✅ **Monitor capacity** (check before launching large jobs)

**Resource Request Cheat Sheet:**
- API: 100m CPU, 256Mi memory
- Processor: 100m CPU, 512Mi memory
- Batch Jobs: 100m CPU, 512Mi-1Gi memory
- Never request >300m CPU for batch jobs (prevents scheduling failures)

**Priority Hierarchy:**
```
service-critical (10000) → Can preempt everything
service-standard (5000)  → Can preempt cron/batch
scheduled-high (1000)    → Can preempt batch
scheduled-standard (500) → Can preempt batch
batch-high (100)         → Can preempt batch-standard
batch-standard (50)      → Default, lowest priority
batch-low (10)           → Only runs with idle capacity
```
