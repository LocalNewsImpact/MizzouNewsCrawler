# Cluster Scaling Decision - URGENT

**Date:** October 19, 2025  
**Status:** 🔴 CRITICAL - Processor cannot schedule, insufficient resources

---

## Current Situation

After increasing processor memory request to 2.5Gi:
- ✅ Cleaned up 57 failed pods
- ✅ Updated memory request to match actual usage
- ❌ **Processor cannot schedule** - no node has enough memory!

### The Math Problem

**e2-standard-2 nodes:**
- Total RAM: 8GB
- System overhead: ~5.2GB (kubelet, OS, system pods)
- **Allocatable: 2.8GB per node**

**Our workload needs:**
- Processor: 2.5GB request
- Argo discovery: 2GB request  
- Argo verification: 1GB request
- API: 256MB request

**Problem:** Cannot fit 2.5GB pod on a 2.8GB node when other pods are present!

---

## Three Options

### Option 1: Scale UP Node Size (RECOMMENDED) ✅

**Change:** Resize nodes from e2-standard-2 → e2-standard-4

**Specs:**
- **Current (e2-standard-2):** 2 vCPU, 8GB RAM → 2.8GB allocatable
- **New (e2-standard-4):** 4 vCPU, 16GB RAM → ~14GB allocatable

**Cost:**
- Current: 3 nodes × $26/month = **$78/month**
- New: 3 nodes × $52/month = **$156/month**
- **Increase: +$78/month (+100%)**

**Pros:**
- ✅ Can run ML workloads comfortably (2.5GB fits easily)
- ✅ Room for multiple concurrent extractions
- ✅ No need to compromise on memory requests
- ✅ Better CPU for ML processing (4 vCPU vs 2)
- ✅ More stable, fewer OOM kills

**Cons:**
- ❌ 2x cost increase
- ❌ Requires node pool recreation (5-10 min downtime)

**Steps:**
```bash
# 1. Create new node pool
gcloud container node-pools create large-nodes \
  --cluster=mizzou-cluster \
  --zone=us-central1-a \
  --machine-type=e2-standard-4 \
  --num-nodes=3 \
  --disk-size=50 \
  --enable-autorepair \
  --enable-autoupgrade

# 2. Cordon old nodes
kubectl cordon -l cloud.google.com/gke-nodepool=large-disk-pool

# 3. Drain old nodes (graceful)
kubectl drain -l cloud.google.com/gke-nodepool=large-disk-pool \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --force

# 4. Delete old node pool
gcloud container node-pools delete large-disk-pool \
  --cluster=mizzou-cluster \
  --zone=us-central1-a
```

---

### Option 2: Reduce Memory Request (QUICK FIX) ⚠️

**Change:** Lower processor memory request from 2.5Gi → 1.8Gi

**Command:**
```bash
kubectl set resources deployment mizzou-processor -n production \
  --requests=memory=1.8Gi,cpu=200m \
  --limits=memory=4Gi,cpu=1
```

**Cost:** $0

**Pros:**
- ✅ Free
- ✅ Immediate (no downtime)
- ✅ Works with current nodes

**Cons:**
- ❌ Still risk of OOM kills (actual usage is 2.2GB)
- ❌ Node overcommitment continues
- ❌ Doesn't fix root cause
- ❌ May crash during entity extraction

**Risk Level:** HIGH - Processor will likely still crash under ML load

---

### Option 3: Add More e2-standard-2 Nodes ⏭️

**Change:** Scale from 3 nodes → 5 nodes

**Cost:**
- Current: 3 nodes × $26/month = $78/month
- New: 5 nodes × $26/month = $130/month
- **Increase: +$52/month (+67%)**

**Pros:**
- ✅ More capacity
- ✅ Spreads load across more nodes

**Cons:**
- ❌ Doesn't solve per-node memory constraint
- ❌ Still can't run 2.5GB pod on 2.8GB allocatable node
- ❌ Argo discovery (2GB) + processor (2.5GB) still won't fit together
- ❌ Inefficient use of resources

**Verdict:** NOT RECOMMENDED - Doesn't solve the problem

---

## Comparison Table

| Metric | Current | Option 1 (e2-std-4) | Option 2 (Reduce req) | Option 3 (Add nodes) |
|--------|---------|---------------------|----------------------|---------------------|
| **Node Type** | e2-std-2 | e2-std-4 | e2-std-2 | e2-std-2 |
| **Nodes** | 3 | 3 | 3 | 5 |
| **Allocatable/node** | 2.8GB | 14GB | 2.8GB | 2.8GB |
| **Total Allocatable** | 8.4GB | 42GB | 8.4GB | 14GB |
| **Cost/month** | $78 | $156 | $78 | $130 |
| **Can fit ML pods?** | ❌ | ✅ | ⚠️ | ❌ |
| **OOM Risk** | HIGH | LOW | MEDIUM | HIGH |
| **Downtime** | - | 5-10 min | None | None |
| **Recommendation** | - | **✅ DO THIS** | ⚠️ Temporary | ❌ Don't do |

---

## Recommended Path Forward

### Immediate (Right Now):
```bash
# Temporary fix to get processor running
kubectl set resources deployment mizzou-processor -n production \
  --requests=memory=1.8Gi,cpu=200m \
  --limits=memory=4Gi,cpu=1

# This allows processor to schedule while we scale up
```

### Within 24 Hours:
```bash
# Scale up to e2-standard-4 nodes (proper fix)
gcloud container node-pools create large-nodes \
  --cluster=mizzou-cluster \
  --zone=us-central1-a \
  --machine-type=e2-standard-4 \
  --num-nodes=3 \
  --disk-size=50

# Then migrate workloads and delete old pool
```

### After Migration:
```bash
# Restore proper memory request
kubectl set resources deployment mizzou-processor -n production \
  --requests=memory=2.5Gi,cpu=500m \
  --limits=memory=6Gi,cpu=2
```

---

## Alternative: Hybrid Approach

**If cost is a major concern:**

1. Keep 2 e2-standard-2 nodes for API/lightweight workloads ($52/month)
2. Add 1 e2-standard-4 node for ML/processor workloads ($52/month)
3. **Total: $104/month** (vs $156 for all e2-std-4)

Use node selectors to schedule ML pods on the larger node:
```yaml
spec:
  nodeSelector:
    cloud.google.com/gke-nodepool: large-nodes
```

This gives us:
- 2 × e2-std-2 = 5.6GB allocatable (for API, webhooks)
- 1 × e2-std-4 = 14GB allocatable (for processor, ML jobs)
- **Total cost: $104/month (+$26/month from current)**

---

## Cost-Benefit Analysis

**Current state:**
- $78/month
- Constant crashes
- Failed extractions
- Manual intervention required daily

**Option 1 (e2-std-4):**
- $156/month (+$78)
- Stable operation
- ML workloads run successfully
- Minimal manual intervention
- **ROI: High** (developer time saved > $78/month)

**Hybrid approach:**
- $104/month (+$26)
- Mostly stable
- ML workloads run on dedicated node
- Good balance of cost and reliability

---

## Decision Matrix

**If budget < $150/month:**
→ Choose **Hybrid Approach** ($104/month)

**If reliability is priority:**
→ Choose **Option 1** (all e2-std-4, $156/month)

**If no budget available:**
→ Choose **Option 2** temporarily (reduce to 1.8Gi)
→ BUT: Plan to scale up within weeks (unsustainable)

---

## My Recommendation

**Implement Hybrid Approach:**

1. **Immediate** (5 minutes):
   ```bash
   # Reduce request temporarily
   kubectl set resources deployment mizzou-processor -n production \
     --requests=memory=1.8Gi,cpu=200m \
     --limits=memory=4Gi,cpu=1
   ```

2. **Today** (30 minutes):
   ```bash
   # Create ML node pool
   gcloud container node-pools create ml-pool \
     --cluster=mizzou-cluster \
     --zone=us-central1-a \
     --machine-type=e2-standard-4 \
     --num-nodes=1 \
     --disk-size=50 \
     --node-labels=workload=ml
   
   # Update processor to use ML node
   kubectl patch deployment mizzou-processor -n production -p '
   spec:
     template:
       spec:
         nodeSelector:
           workload: ml
   '
   
   # Restore proper memory request
   kubectl set resources deployment mizzou-processor -n production \
     --requests=memory=2.5Gi,cpu=500m \
     --limits=memory=6Gi,cpu=2
   ```

3. **Tomorrow** (cleanup):
   ```bash
   # Scale down old pool from 3 to 2 nodes
   gcloud container node-pools update large-disk-pool \
     --cluster=mizzou-cluster \
     --zone=us-central1-a \
     --num-nodes=2
   ```

**Result:**
- Cost: $104/month (+$26, or 33% increase)
- Stability: High
- ML performance: Good
- Future-proof: Can add more ML nodes as needed

---

**Next Action:** Which option do you want to implement?

1. Immediate temporary fix (1.8Gi request)
2. Hybrid approach (1 ML node)
3. Full upgrade (all e2-std-4 nodes)
