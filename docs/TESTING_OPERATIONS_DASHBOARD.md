# Testing Operations Dashboard Locally with Live Data

## Quick Start (5 minutes)

### **Step 1: Commit and Deploy Your Changes**

First, let's get your changes into production:

```bash
# Add all the new telemetry files
git add backend/app/telemetry/operations.py \
        backend/app/main.py \
        web/frontend/src/OperationsDashboard.jsx \
        web/frontend/src/App.jsx \
        docs/OPERATIONS_TELEMETRY.md

# Commit
git commit -m "Add operations telemetry dashboard for real-time pod monitoring"

# Push to feature branch
git push origin feature/gcp-kubernetes-deployment

# Trigger API rebuild (includes new endpoints)
gcloud builds triggers run build-api-manual \
    --branch=feature/gcp-kubernetes-deployment \
    --substitutions=_IMAGE_TAG=$(git rev-parse --short HEAD)
```

⏱️ **Wait 5-10 minutes for API build to complete and deploy**

---

### **Step 2: Port-Forward Production API**

Once the API pod restarts with new code:

```bash
# Run the test script
./scripts/test-operations-dashboard-local.sh
```

This will:
- Find your production API pod
- Port-forward it to `localhost:8000`
- Keep running (Ctrl+C to stop)

**Leave this terminal open!**

---

### **Step 3: Update Frontend Proxy Config**

Your frontend (`localhost:5173`) needs to proxy API requests to `localhost:8000`.

Check if `web/frontend/vite.config.js` has proxy config:

```javascript
export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  }
})
```

If not already configured, the frontend will make requests directly to the port-forwarded API.

---

### **Step 4: Open the Dashboard**

1. Open browser to: **http://localhost:5173**
2. Click the **"🚀 Operations"** tab
3. You should see:
   - ✅ System health indicator
   - ✅ Queue depth cards (with live numbers!)
   - ✅ Processing velocity metrics
   - ✅ Active sources table (what's being crawled RIGHT NOW)
   - ✅ Auto-refresh every 10 seconds

---

## Test the Endpoints Directly

You can also test the raw API endpoints:

```bash
# Queue status (should show current queue depths)
curl http://localhost:8000/api/telemetry/operations/queue-status | jq

# Recent activity (items processed in last 5 minutes)
curl http://localhost:8000/api/telemetry/operations/recent-activity?minutes=5 | jq

# Active sources (what's being crawled now)
curl http://localhost:8000/api/telemetry/operations/sources-being-processed?limit=10 | jq

# System health
curl http://localhost:8000/api/telemetry/operations/health | jq

# County progress
curl http://localhost:8000/api/telemetry/operations/county-progress | jq

# Recent errors
curl http://localhost:8000/api/telemetry/operations/recent-errors?hours=1 | jq
```

---

## What You Should See

### **If Everything Works** ✅

- **Queue Status**: Real numbers like `verification_pending: 1234`
- **Active Sources**: List of sources with timestamps from last 15 minutes
- **Processing Velocity**: Non-zero counts if pods are actively processing
- **System Health**: Green "healthy" status (or yellow/red if issues detected)

### **Example Healthy Response**

```json
{
  "status": "healthy",
  "issues": [],
  "metrics": {
    "error_rate_pct": 2.3,
    "articles_last_hour": 145,
    "errors_last_hour": 3,
    "url_velocity_change_pct": 5.2
  }
}
```

### **If No Activity** 🤔

If all queues show `0` and no active sources:
- ✅ This is normal if crawler/processor pods are idle
- ✅ Try triggering a crawl manually to generate activity
- ✅ Check if continuous processor is running: `kubectl get pods -n production | grep processor`

---

## Alternative: Test with Local API + Cloud SQL Proxy

If you want to run the **entire stack locally** (API + Frontend):

### **Step 1: Start Cloud SQL Proxy**

```bash
# Download Cloud SQL Proxy if you don't have it
# https://cloud.google.com/sql/docs/mysql/sql-proxy

# Run proxy (replace with your instance connection name)
cloud-sql-proxy mizzou-news-crawler:us-central1:mizzou-db-prod \
    --port 5432
```

### **Step 2: Set Environment Variables**

```bash
export DATABASE_HOST=localhost
export DATABASE_PORT=5432
export DATABASE_NAME=mizzou_news
export DATABASE_USER=postgres
export DATABASE_PASSWORD=<your-password>
export USE_CLOUD_SQL_CONNECTOR=false
```

### **Step 3: Run API Locally**

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

### **Step 4: Run Frontend**

```bash
cd web/frontend
npm run dev
```

Now open http://localhost:5173 and click "🚀 Operations"!

---

## Troubleshooting

### **Port 8000 already in use**

```bash
# Kill existing process on 8000
lsof -ti:8000 | xargs kill -9

# Or use different port
kubectl port-forward -n production <pod-name> 8001:8000
```

Then update frontend proxy to target `:8001`.

### **No data showing in dashboard**

1. Check API is responding:
   ```bash
   curl http://localhost:8000/health
   ```

2. Check browser console for errors (F12 → Console)

3. Verify endpoints return data:
   ```bash
   curl http://localhost:8000/api/telemetry/operations/queue-status
   ```

4. Check if API pod has new code:
   ```bash
   kubectl describe pod -n production <api-pod-name> | grep Image
   # Should show your latest commit SHA as image tag
   ```

### **CORS errors**

If you see CORS errors in browser console:
- The API's CORS middleware should allow `localhost:5173`
- Check `backend/app/main.py` has `allow_origins=["*"]` or includes your localhost

### **404 on telemetry endpoints**

If `/api/telemetry/operations/*` returns 404:
- API doesn't have the new code yet
- Check build status: `gcloud builds list --limit=3`
- Wait for build to complete and pod to restart
- Verify pod image tag matches your commit

---

## Quick Validation Checklist

- [ ] API build completed successfully
- [ ] API pod restarted with new image (check image tag)
- [ ] Port-forward is active (`localhost:8000` responding)
- [ ] Frontend is running (`localhost:5173`)
- [ ] Can access http://localhost:5173
- [ ] "🚀 Operations" tab is visible in navigation
- [ ] Clicking tab shows the dashboard (not blank page)
- [ ] Queue status cards show numbers (even if zeros)
- [ ] No console errors in browser DevTools
- [ ] Dashboard auto-refreshes every 10 seconds

---

## Next Steps After Testing

Once verified locally:

1. **Merge to main** (if using feature branch)
2. **Deploy to production** (if not auto-deployed)
3. **Share with team** - Give them the direct link to operations tab
4. **Set up monitoring alerts** (future enhancement)
5. **Add to runbooks** - Reference this dashboard for troubleshooting

---

## Pro Tips 💡

1. **Keep port-forward running** in a dedicated terminal tab
2. **Use browser DevTools Network tab** to see API requests/responses
3. **Test during active crawl** to see real-time updates
4. **Compare queue depths** before/after processor runs
5. **Watch for velocity changes** when tuning batch sizes
6. **Export data** by copying JSON responses for analysis

Happy monitoring! 🚀📊
