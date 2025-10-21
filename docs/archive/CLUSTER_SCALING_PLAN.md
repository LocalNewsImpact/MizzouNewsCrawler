# Cluster Scaling Plan - Upgrade to Larger Nodes

**Date:** October 19, 2025  
**Status:** 🟡 Ready for Execution  
**Priority:** HIGH - Resolves immediate capacity constraints

---

## Current State

**Node Pool:** `large-disk-pool`
- **Machine Type:** e2-medium (2 vCPU, 4GB RAM)
- **Disk:** 100GB SSD
- **Autoscaling:** 2-5 nodes
- **Current Nodes:** 4 nodes
- **Allocatable per Node:** ~2.8GB RAM
- **Monthly Cost:** ~$70 (4 × $17.52)

**Problem:**
- Processor needs 2.5GB RAM for ML workloads
- Argo workflows need 2GB RAM
- Cannot fit both on same node with e2-medium
- Constant OOM kills and pod failures

---

## Proposed Solution

**New Node Pool:** `standard-pool`
- **Machine Type:** e2-standard-4 (4 vCPU, 16GB RAM)
- **Disk:** 100GB SSD
- **Autoscaling:** 2-4 nodes
- **Allocatable per Node:** ~14GB RAM
- **Monthly Cost:** ~$104 (2 × $52.09)

**Benefits:**
- ✅ **5x more memory per node** (14GB vs 2.8GB)
- ✅ **2x more CPU per node** (4 vCPU vs 2 vCPU)
- ✅ Processor + Argo workflows fit comfortably on same node
- ✅ Room for 5-6 processor pods per node (2.5GB each)
- ✅ No more OOM kills
- ✅ Better burst capacity for ML workloads

---

## Cost Analysis

### Current Configuration (e2-medium)
```
4 nodes × $17.52/month = $70.08/month
```

### Proposed Configuration (e2-standard-4)
```
2 nodes × $52.09/month = $104.18/month
Can scale to 4 nodes = $208.36/month (peak)
```

### Cost Impact
- **Base Cost:** +$34/month (+49%)
- **Peak Cost:** +$138/month (+197%) if all 4 nodes needed
- **Cost per GB RAM:** **Lower** with e2-standard-4
  - e2-medium: $17.52 / 2.8GB = $6.26/GB
  - e2-standard-4: $52.09 / 14GB = $3.72/GB ✅

### Cost Optimization
With better capacity, we can likely run on **2 nodes most of the time** instead of 4:
- **Current:** 4 × e2-medium = $70/month
- **Proposed:** 2 × e2-standard-4 = $104/month
- **Net increase:** $34/month for 2x more capacity

---

## Migration Plan

### Phase 1: Create New Node Pool (10 minutes)

```bash
# Run the upgrade script
bash /tmp/node_pool_upgrade.sh
```

**What it does:**
1. Creates new node pool with e2-standard-4 nodes
2. Waits for nodes to be ready
3. Cordons old nodes (prevents new pods)
4. Drains old nodes (migrates existing pods)
5. Waits for migration to complete

**Expected timeline:**
- Node pool creation: 3-5 minutes
- Pod migration: 2-3 minutes
- Total: ~10 minutes

---

### Phase 2: Verify Migration (5 minutes)

```bash
# Check all pods are running on new nodes
kubectl get pods -n production -o wide

# Verify node resources
kubectl top nodes

# Check for any issues
kubectl get events -n production --sort-by='.lastTimestamp' | tail -20
```

**Success criteria:**
- ✅ All pods in "Running" state
- ✅ All pods on nodes with label `pool=standard`
- ✅ Node memory usage < 80%
- ✅ No pending pods

---

### Phase 3: Delete Old Node Pool (2 minutes)

**Only after verifying Phase 2 is successful!**

```bash
# Delete the old node pool
gcloud container node-pools delete large-disk-pool \
  --cluster=mizzou-cluster \
  --zone=us-central1-a \
  --quiet
```

**What happens:**
- Old nodes are removed from cluster
- No impact on running pods (they're already migrated)
- Cost savings from old nodes stop immediately

---

### Phase 4: Update Processor Resources (1 minute)

Now that we have more capacity, restore the proper memory request:

```bash
# Set processor to proper ML memory requirements
kubectl set resources deployment mizzou-processor -n production \
  --requests=memory=2.5Gi,cpu=200m \
  --limits=memory=4Gi,cpu=1
```

---

## Rollback Plan

If something goes wrong during migration:

```bash
# 1. Uncordon old nodes
kubectl get nodes -l cloud.google.com/gke-nodepool=large-disk-pool -o name | \
  xargs -I {} kubectl uncordon {}

# 2. Delete new node pool
gcloud container node-pools delete standard-pool \
  --cluster=mizzou-cluster \
  --zone=us-central1-a \
  --quiet

# 3. Pods will reschedule back to old nodes automatically
kubectl get pods -n production -w
```

---

## Alternative: Scale Existing Pool

Instead of creating a new pool, we could scale the existing pool:

```bash
# Just add more e2-medium nodes
gcloud container node-pools update large-disk-pool \
  --cluster=mizzou-cluster \
  --zone=us-central1-a \
  --max-nodes=8

# Manually scale to 8 nodes
gcloud container clusters resize mizzou-cluster \
  --node-pool=large-disk-pool \
  --num-nodes=8 \
  --zone=us-central1-a
```

**Comparison:**

| Option | Nodes | Total RAM | Total Cost | RAM/$ | Recommendation |
|--------|-------|-----------|------------|-------|----------------|
| **Scale e2-medium** | 8 | 22.4GB | $140/mo | 0.16 GB/$ | ❌ Wasteful |
| **Upgrade to e2-standard-4** | 2 | 28GB | $104/mo | 0.27 GB/$ | ✅ Better |

The upgrade path is **more cost-efficient** and provides better resource density.

---

## Additional Node Pool (Optional)

For dedicated ML workloads, we could also add a separate ML node pool:

```bash
# Create dedicated ML node pool
gcloud container node-pools create ml-pool \
  --cluster=mizzou-cluster \
  --zone=us-central1-a \
  --machine-type=n2-highmem-2 \  # 2 vCPU, 16GB RAM, optimized for memory
  --disk-size=100 \
  --num-nodes=1 \
  --enable-autoscaling \
  --min-nodes=0 \  # Scale to zero when not needed!
  --max-nodes=2 \
  --node-labels=workload=ml \
  --node-taints=workload=ml:NoSchedule  # Only ML pods scheduled here
```

Then update processor deployment:
```yaml
spec:
  template:
    spec:
      nodeSelector:
        workload: ml
      tolerations:
      - key: workload
        operator: Equal
        value: ml
        effect: NoSchedule
```

**Cost:** $61/month (when running), $0/month (when scaled to zero)

---

## Recommended Approach

### Option 1: Simple Upgrade (Recommended)
- Replace e2-medium with e2-standard-4
- 2-4 node autoscaling
- **Cost:** $104-208/month
- **Complexity:** Low
- **Timeline:** 15 minutes

### Option 2: Hybrid Pools (Advanced)
- Keep e2-medium for API/webhooks (cheap)
- Add e2-standard-4 for processor (capacity)
- Add n2-highmem-2 for ML (dedicated, scale to zero)
- **Cost:** $70 + $104 + $0-61 = $174-235/month
- **Complexity:** Medium
- **Timeline:** 30 minutes
- **Benefit:** Better resource separation, cost optimization

### Option 3: Scale Existing (Not Recommended)
- Scale e2-medium from 4 to 8 nodes
- **Cost:** $140/month
- **Complexity:** Very low
- **Timeline:** 5 minutes
- **Downside:** Wasteful, poor resource density

---

## Decision Matrix

| Criteria | Option 1: Upgrade | Option 2: Hybrid | Option 3: Scale |
|----------|-------------------|------------------|-----------------|
| **Cost** | $104-208/mo | $174-235/mo | $140/mo |
| **RAM per $** | ✅ 0.27 GB/$ | ✅ 0.25 GB/$ | ❌ 0.16 GB/$ |
| **Complexity** | ✅ Low | ⚠️ Medium | ✅ Very Low |
| **Timeline** | ✅ 15 min | ⚠️ 30 min | ✅ 5 min |
| **Future-proof** | ✅ Yes | ✅✅ Best | ❌ No |
| **Recommendation** | ✅ **YES** | ⭐ Advanced | ❌ Avoid |

---

## Execution Steps

**RECOMMENDED: Option 1 - Simple Upgrade**

```bash
# 1. Run upgrade script
bash /tmp/node_pool_upgrade.sh

# 2. Wait for completion (~10 minutes)
# Script will pause and ask for confirmation

# 3. Verify all pods running
kubectl get pods -n production -o wide

# 4. Delete old node pool
gcloud container node-pools delete large-disk-pool \
  --cluster=mizzou-cluster \
  --zone=us-central1-a \
  --quiet

# 5. Restore proper processor memory
kubectl set resources deployment mizzou-processor -n production \
  --requests=memory=2.5Gi,cpu=200m \
  --limits=memory=4Gi,cpu=1

# 6. Verify processor starts successfully
kubectl rollout status deployment/mizzou-processor -n production
kubectl logs -n production -l app=mizzou-processor --tail=50

# 7. Monitor for 30 minutes
watch kubectl get pods -n production
```

---

## Post-Migration Checklist

- [ ] All pods in Running state
- [ ] No pods on old node pool
- [ ] Node memory usage < 80%
- [ ] Processor completes entity extraction without OOM
- [ ] Argo workflows run successfully
- [ ] No pending pods for 30 minutes
- [ ] Cost monitoring alert configured
- [ ] Old node pool deleted
- [ ] Documentation updated

---

## Monitoring After Migration

```bash
# Watch node resources
watch kubectl top nodes

# Watch pod distribution
watch 'kubectl get pods -n production -o wide | grep -E "(NAME|mizzou)"'

# Check for OOM kills
kubectl get events -n production | grep OOM

# Monitor costs
gcloud billing accounts get-iam-policy ACCOUNT_ID
```

Set up alerts:
- Node memory > 85%
- Node CPU > 90%
- Pod OOM events
- Monthly cost > $250

---

## Expected Outcomes

**Before Migration:**
- 4 × e2-medium (2.8GB allocatable each)
- Processor crashes with OOM
- Cannot schedule pods
- Constant pod failures

**After Migration:**
- 2 × e2-standard-4 (14GB allocatable each)
- Processor runs reliably
- Room for 5-6 processor pods per node
- No OOM kills
- Better cost efficiency ($/GB)

---

**Status:** ✅ Ready to execute  
**Risk Level:** 🟢 Low (tested migration procedure)  
**Estimated Downtime:** None (rolling migration)  
**Approval Required:** Yes (cost increase)  
**Timeline:** 15 minutes execution + 30 minutes monitoring
