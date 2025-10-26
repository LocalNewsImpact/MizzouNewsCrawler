# Cluster Capacity Crisis Analysis

**Date:** October 19, 2025  
**Status:** 🔴 CRITICAL - Cluster at capacity, pods failing due to resource exhaustion

---

## Problem Summary

The GKE cluster is constantly running into capacity constraints due to **structural issues**, not insufficient capacity.

### Current State
- ✅ **4 nodes** in the cluster (e2-standard-2: 2 vCPU, 8GB RAM each)
- ❌ **45 failed processor pods** not cleaned up (consuming IP addresses, taking up pod slots)
- ❌ **1 node at 111% memory** usage (out of memory!)
- ❌ New pods cannot schedule due to "Insufficient memory" errors
- ❌ ML entity extraction pods crash with OOM (exit code 137)

---

## Root Causes

### 1. **Failed Pod Cleanup Not Configured** (PRIMARY ISSUE)

**Problem:**
- Kubernetes by default keeps failed pods **indefinitely**
- We have **45 failed processor pods** from the last 18 hours
- Each failed pod:
  - Consumes an IP address
  - Takes up a pod slot
  - Prevents resource reclamation

**Evidence:**
```bash
kubectl get pods -n production | grep mizzou-processor
# Shows 45 pods, only 1 is Running, 44 are Error/ContainerStatusUnknown

kubectl get replicasets -n production | grep mizzou-processor
# Shows 11 replica sets from multiple deployments over 34 hours
```

**Why pods are failing:**
- Entity extraction with spaCy loads **2.2GB** of ML models into memory
- Pod has 1GB request, 4GB limit
- When multiple entity extractions run concurrently → OOM kill (exit 137)
- Pod crashes, Kubernetes recreates it → crashes again → cycle continues

---

### 2. **Resource Requests vs Usage Mismatch**

**Current Configuration:**
```yaml
processor:
  requests:
    memory: 1Gi    # ← Too low!
    cpu: 100m
  limits:
    memory: 4Gi
    cpu: 1
```

**Actual Usage:**
- Normal operation (no ML): **500MB-800MB**
- During entity extraction: **2.2GB-2.5GB**
- Peak spikes: Can hit **3GB+**

**Problem:**
- Request is 1GB but actual usage is 2.2GB
- Kubernetes schedules based on *requests*, not *limits*
- Node can become overcommitted (111% memory usage observed)

---

### 3. **No Pod Disruption Budget or Resource Quotas**

**Missing:**
- No `PodDisruptionBudget` to ensure availability during evictions
- No `ResourceQuota` to prevent runaway pod creation
- No `LimitRange` to enforce reasonable defaults
- No pod anti-affinity to spread load across nodes

---

### 4. **Workflow Pods Not Cleaned Up After Completion**

**Argo Workflow pods** (discovery, verification, extraction) remain after completion:
```bash
mizzou-news-pipeline-1760853600-discovery-step-1314550828
mizzou-news-pipeline-1760853600-verification-step-2881498061
```

These request **2GB** and **1GB** respectively, consuming scarce cluster memory.

---

## Impact Analysis

### Memory Capacity Breakdown (per node)

**Total available:** 8GB RAM per node

**Current allocations:**
- System overhead: ~500MB
- kubelet/kube-proxy: ~200MB
- **Available for pods:** ~7.3GB

**Current requests (node `tlfp`):**
- 44 failed processor pods × 1GB request = **44GB requested** (!)
- Actual running pod: 1 × 2.2GB = 2.2GB used
- Argo discovery pod: 2GB request
- Argo verification pod: 1GB request

**Result:** Severe overcommitment, new pods cannot schedule

---

## Solutions

### Immediate Actions (Next 15 minutes)

#### 1. Clean Up Failed Pods
```bash
# Delete all failed/unknown pods
kubectl delete pods -n production \
  --field-selector status.phase=Failed,status.phase=Unknown

# Delete old replica sets (keeps last 2)
kubectl delete rs -n production \
  $(kubectl get rs -n production -o json | \
    jq -r '.items[] | select(.spec.replicas==0) | select(.metadata.creationTimestamp < (now - 86400 | strftime("%Y-%m-%dT%H:%M:%SZ"))) | .metadata.name')
```

**Expected impact:**
- Free up 44 pod slots
- Reclaim IP addresses
- Clear scheduler queue

---

#### 2. Configure Automatic Pod Cleanup

Add to `k8s/processor-deployment.yaml`:
```yaml
spec:
  template:
    spec:
      restartPolicy: Never  # Don't auto-restart failed pods
      # OR
      ttlSecondsAfterFinished: 3600  # Clean up after 1 hour (for Jobs)
```

For Deployments, set pod GC thresholds:
```bash
# Add to kube-controller-manager flags (requires cluster admin)
--terminated-pod-gc-threshold=10  # Keep max 10 terminated pods
```

Or use a CronJob:
```yaml
# k8s/cleanup-failed-pods-cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: cleanup-failed-pods
  namespace: production
spec:
  schedule: "*/15 * * * *"  # Every 15 minutes
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: pod-cleaner
          containers:
          - name: kubectl
            image: bitnami/kubectl:latest
            command:
            - /bin/sh
            - -c
            - |
              kubectl delete pods -n production \
                --field-selector status.phase=Failed \
                --field-selector status.phase=Unknown \
                --grace-period=0 --force
          restartPolicy: Never
```

---

#### 3. Fix Processor Memory Requests

Update `k8s/processor-deployment.yaml`:
```yaml
spec:
  template:
    spec:
      containers:
      - name: processor
        resources:
          requests:
            memory: 2.5Gi  # ← Increased to match actual ML usage
            cpu: 200m      # ← Slight increase for ML workload
          limits:
            memory: 4Gi
            cpu: 1
```

**Rationale:**
- 2.5GB request matches observed peak usage (2.2GB + buffer)
- Prevents node overcommitment
- Still allows 3 pods per 8GB node (3 × 2.5GB = 7.5GB)

---

#### 4. Configure Argo Workflow Cleanup

Add to Argo Workflow spec:
```yaml
spec:
  ttlStrategy:
    secondsAfterCompletion: 3600  # Delete pods 1 hour after completion
    secondsAfterSuccess: 1800     # Delete successful pods after 30 min
    secondsAfterFailure: 7200     # Keep failed pods for 2 hours (debugging)
  
  podGC:
    strategy: OnPodSuccess  # Clean up successful pods immediately
```

---

### Short-term Improvements (This Week)

#### 5. Implement Pod Anti-Affinity

Spread processor pods across nodes:
```yaml
spec:
  template:
    spec:
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchExpressions:
                - key: app
                  operator: In
                  values:
                  - mizzou-processor
              topologyKey: kubernetes.io/hostname
```

---

#### 6. Add Resource Quotas

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: production-quota
  namespace: production
spec:
  hard:
    requests.cpu: "8"        # 4 nodes × 2 vCPU
    requests.memory: 24Gi    # 4 nodes × 6GB (leaving headroom)
    limits.cpu: "16"
    limits.memory: 32Gi
    pods: "50"               # Limit total pods
```

---

#### 7. Separate ML Workloads to Different Nodes

Create a dedicated node pool for ML workloads:
```bash
gcloud container node-pools create ml-pool \
  --cluster=mizzou-cluster \
  --zone=us-central1-a \
  --machine-type=e2-standard-4 \  # 4 vCPU, 16GB RAM
  --num-nodes=1 \
  --node-labels=workload=ml \
  --enable-autoscaling \
  --min-nodes=1 \
  --max-nodes=2
```

Then add node selector to processor deployment:
```yaml
spec:
  template:
    spec:
      nodeSelector:
        workload: ml  # Schedule ML pods on dedicated nodes
```

---

### Long-term Architecture Changes (Next Sprint)

#### 8. Move Entity Extraction to Async Job Queue

**Current:** Entity extraction runs inline during article processing  
**Problem:** Spiky memory usage, crashes, blocks other processing

**Solution:** Use Cloud Tasks or Pub/Sub for async entity extraction

```python
# After article extraction
if article.needs_entity_extraction:
    # Enqueue async job instead of processing inline
    task_client.create_task(
        parent=queue_path,
        task={
            'app_engine_http_request': {
                'relative_uri': '/api/entity-extraction',
                'body': json.dumps({'article_id': article.id}).encode()
            }
        }
    )
```

**Benefits:**
- Decouple ML from main pipeline
- Better resource utilization
- Easier to scale independently
- Can batch entity extraction for efficiency

---

#### 9. Implement Caching for ML Models

spaCy loads **entire model** (500MB+) for each article:
```python
# Current: Loads model every time
nlp = spacy.load("en_core_web_lg")  # 500MB disk, 2GB memory

# Better: Load once, cache in memory
@lru_cache(maxsize=1)
def get_nlp_model():
    return spacy.load("en_core_web_lg")

nlp = get_nlp_model()  # Reuses cached model
```

**Expected savings:** 80% reduction in memory spikes

---

#### 10. Schedule ML Workloads During Off-Peak Hours

Run entity extraction in batches during low-traffic periods:
```yaml
# CronJob for batch entity extraction
apiVersion: batch/v1
kind: CronJob
metadata:
  name: entity-extraction-batch
spec:
  schedule: "0 2 * * *"  # 2 AM daily
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: entity-extractor
            image: mizzou-processor:latest
            command: ["python", "-m", "src.cli.cli_modular", "extract-entities", "--batch-size", "100"]
            resources:
              requests:
                memory: 4Gi
                cpu: 1
              limits:
                memory: 8Gi
                cpu: 2
```

---

## Capacity Planning

### Current vs Recommended

| Component | Current | Recommended | Why |
|-----------|---------|-------------|-----|
| **Processor Memory Request** | 1Gi | 2.5Gi | Match actual ML usage |
| **Processor Replicas** | 1 | 2-3 | High availability |
| **Node Pool** | 1 pool (e2-standard-2) | 2 pools (regular + ML) | Separate concerns |
| **Pod Cleanup** | None | 15min CronJob | Prevent accumulation |
| **Resource Quotas** | None | Enforced | Prevent overcommitment |
| **Failed Pod Retention** | Infinite | 1 hour | Free resources |

### Cost Impact

**Current:** 4 × e2-standard-2 = **$104/month**

**Option A: Fix Structure (Recommended)**
- Same 4 nodes
- Better utilization through proper requests
- Add 1 ML node (e2-standard-4) for peak periods
- **Cost:** $104 + $52 = **$156/month** (+50%)
- **Benefit:** Reliable, no crashes, proper separation

**Option B: Scale Up**
- Add 2 more e2-standard-2 nodes
- Keep current structure
- **Cost:** $104 + $52 = **$156/month** (+50%)
- **Benefit:** More capacity but same structural issues

**Recommendation:** Option A - Fix structure + dedicated ML node

---

## Decision Tree

```
Do you need entity extraction real-time?
├─ YES → Implement Option A (dedicated ML node pool)
│         + Model caching
│         + Pod cleanup automation
│         Cost: +$52/month
│
└─ NO  → Move entity extraction to batch job (2 AM daily)
          + Keep current 4 nodes
          + Pod cleanup automation
          Cost: $0
          Complexity: Medium (requires async queue)
```

---

## Immediate Action Items

**Priority 1 (Do Now):**
1. ☐ Delete failed pods: `kubectl delete pods -n production --field-selector status.phase=Failed`
2. ☐ Update processor memory requests to 2.5Gi
3. ☐ Deploy pod cleanup CronJob
4. ☐ Configure Argo workflow TTL

**Priority 2 (This Week):**
5. ☐ Add pod anti-affinity rules
6. ☐ Implement ML model caching
7. ☐ Set up resource quotas
8. ☐ Monitor memory usage patterns

**Priority 3 (Next Sprint):**
9. ☐ Decide: Real-time vs batch entity extraction
10. ☐ Implement chosen architecture
11. ☐ Consider dedicated ML node pool if real-time needed

---

## Success Metrics

After fixes, monitor:
- ✅ Node memory usage < 80%
- ✅ No failed pods older than 1 hour
- ✅ Pod scheduling success rate > 99%
- ✅ Entity extraction completion rate > 95%
- ✅ Average pod lifetime > 24 hours (no crashes)

---

**Status:** Ready for implementation  
**Owner:** DevOps/Platform Team  
**Estimated Time:** 2-3 hours for immediate fixes, 1 week for long-term improvements
