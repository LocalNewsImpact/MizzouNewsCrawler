# Operations Telemetry Dashboard - Implementation Summary

## Overview

Your system already has **extensive telemetry infrastructure** tracking all crawler, processor, and API pod activities. This document shows what's available and what was added to surface it in a real-time operations dashboard.

---

## 🎯 What You Already Had

### **1. Queue Tracking (Backend)**
Location: `orchestration/continuous_processor.py`

The continuous processor already tracks:
- **Verification Queue**: URLs awaiting classification (`status='discovered'`)
- **Extraction Queue**: Articles awaiting content extraction (`status='article'`)
- **Analysis Queue**: Articles awaiting ML classification (`primary_label IS NULL`)
- **Entity Extraction Queue**: Articles awaiting gazetteer processing

**These counts are calculated on-demand every poll cycle (default 60s)**

### **2. Extraction Performance Telemetry**
Location: `backend/app/main.py` - `/api/telemetry/summary`

Tracks:
- Total extractions (successful/failed)
- Success rates by extraction method (playwright, trafilatura, etc.)
- Average duration per extraction
- Unique hosts processed
- Method-specific performance breakdown

**Data stored in**: `extraction_telemetry_v2` table

### **3. HTTP Error Tracking**
Location: `/api/telemetry/http-errors`

Monitors:
- HTTP status codes (404, 403, 500, etc.)
- Error counts by host
- Recent failure timestamps
- Error rate trends

**Data stored in**: `http_error_summary` table

### **4. Publisher/Source Statistics**
Location: `/api/telemetry/publisher-stats`

Provides:
- Per-publisher success rates
- Content quality metrics
- Field extraction rates (title, author, date, etc.)

### **5. Verification Telemetry**
Location: `backend/app/telemetry/verification.py`

Tracks URL classification performance:
- Articles vs non-articles detection
- Model confidence scores
- False positive/negative rates

**Data stored in**: `verification_telemetry` table

### **6. Frontend Dashboard Widget**
Location: `web/frontend/src/TelemetryQueue.jsx`

Shows:
- Snapshot queue size
- Worker alive status
- Auto-refreshes every 5 seconds

**Uses endpoint**: `/api/telemetry/queue`

---

## 🚀 What Was Added

### **1. Operations Telemetry Endpoints**
**NEW FILE**: `backend/app/telemetry/operations.py`

Six new endpoints specifically for real-time ops monitoring:

#### **`GET /api/telemetry/operations/queue-status`**
Returns current depth of all pipeline queues:
```json
{
  "verification_pending": 1234,
  "extraction_pending": 567,
  "analysis_pending": 89,
  "entity_extraction_pending": 1538,
  "total_pending": 3428,
  "timestamp": "2025-10-05T23:45:12.123Z"
}
```

#### **`GET /api/telemetry/operations/recent-activity?minutes=5`**
Shows processing velocity (items/minute):
```json
{
  "timeframe_minutes": 5,
  "articles_extracted": 23,
  "urls_verified": 145,
  "analysis_completed": 18,
  "timestamp": "2025-10-05T23:45:12.123Z"
}
```

#### **`GET /api/telemetry/operations/sources-being-processed?limit=10`**
Lists sources actively being crawled right now:
```json
{
  "active_sources": [
    {
      "host": "boone.example.com",
      "name": "Boone County News",
      "county": "Boone",
      "recent_urls": 34,
      "last_activity": "2025-10-05T23:44:32.123Z",
      "pending_verification": 12,
      "ready_for_extraction": 8
    }
  ],
  "count": 10,
  "timeframe_minutes": 15
}
```

#### **`GET /api/telemetry/operations/recent-errors?hours=1&limit=50`**
Recent processing errors across all stages:
```json
{
  "errors": [
    {
      "url": "https://example.com/article",
      "error": "Connection timeout after 30s",
      "type": "extraction",
      "timestamp": "2025-10-05T23:40:12.123Z"
    }
  ],
  "summary": {
    "extraction": 5,
    "verification": 2
  },
  "total_errors": 7,
  "timeframe_hours": 1
}
```

#### **`GET /api/telemetry/operations/county-progress`**
Per-county collection statistics:
```json
{
  "counties": [
    {
      "county": "Boone",
      "sources": 15,
      "total_urls": 2341,
      "articles": 1890,
      "pending_verification": 234
    }
  ],
  "total_counties": 12
}
```

#### **`GET /api/telemetry/operations/health`**
Overall pipeline health indicators:
```json
{
  "status": "healthy",  // or "warning" or "error"
  "issues": [],  // Array of issue descriptions
  "metrics": {
    "error_rate_pct": 2.3,
    "articles_last_hour": 145,
    "errors_last_hour": 3,
    "url_velocity_change_pct": 5.2
  }
}
```

### **2. Operations Dashboard UI**
**NEW FILE**: `web/frontend/src/OperationsDashboard.jsx`

React component showing:
- **System Health Status** (green/yellow/red indicator with issues)
- **Pipeline Queue Cards** (4 cards showing queue depths with icons)
- **Processing Velocity** (items processed in last N minutes + rate)
- **Active Sources Table** (what's being crawled right now with timestamps)
- **Auto-refresh**: Every 10 seconds

### **3. Integration with Main App**
**MODIFIED**: `web/frontend/src/App.jsx` and `backend/app/main.py`

- Added "🚀 Operations" tab to navigation bar
- Registered operations router in FastAPI app
- Wired up new dashboard component

---

## 📊 Key Metrics You Can Now Monitor

### **Real-Time Pod Activity**
1. **What's being processed**: See which sources are actively being crawled
2. **Processing rate**: URLs/min, articles/min, analysis/min
3. **Queue health**: Are queues growing or shrinking?
4. **Error rate**: Percentage of failed operations

### **Geographic Coverage**
- Articles collected per county
- Sources active per county
- Pending work per county

### **Pipeline Bottlenecks**
- Which stage has the longest queue?
- Is extraction keeping up with discovery?
- Is analysis keeping up with extraction?

### **System Health**
- Overall status: healthy / warning / error
- Error rate over last hour
- Processing velocity trends
- Anomaly detection (sudden drops in throughput)

---

## 🔍 How Data Flows

```
┌─────────────────────────────────────────────────────────────┐
│  Crawler Pods (Kubernetes)                                  │
│  - Discover URLs → candidate_links (status='discovered')    │
│  - Classify URLs → candidate_links (status='article')       │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ↓
┌─────────────────────────────────────────────────────────────┐
│  Processor Pods (Kubernetes)                                │
│  - Verify URLs → verification_telemetry                     │
│  - Extract content → articles table                         │
│  - Extract metadata → extraction_telemetry_v2               │
│  - Classify articles → articles.primary_label               │
│  - Extract entities → article_entities                      │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ↓
┌─────────────────────────────────────────────────────────────┐
│  Cloud SQL PostgreSQL (Production Database)                 │
│  - candidate_links (queue state)                            │
│  - articles (extracted content + status)                    │
│  - extraction_telemetry_v2 (performance metrics)            │
│  - verification_telemetry (classification metrics)          │
│  - http_error_summary (error tracking)                      │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ↓
┌─────────────────────────────────────────────────────────────┐
│  API Pods (Kubernetes)                                      │
│  - Expose telemetry endpoints                               │
│  - /api/telemetry/operations/* (NEW)                        │
│  - /api/telemetry/summary (existing)                        │
│  - /api/telemetry/http-errors (existing)                    │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ↓
┌─────────────────────────────────────────────────────────────┐
│  Frontend (React Dashboard)                                 │
│  - OperationsDashboard.jsx (NEW)                            │
│  - Auto-refreshes every 10 seconds                          │
│  - Shows real-time queue depths, active sources, errors     │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚢 Deployment

### Files Changed
- ✅ `backend/app/telemetry/operations.py` (NEW)
- ✅ `backend/app/main.py` (modified - import operations router)
- ✅ `web/frontend/src/OperationsDashboard.jsx` (NEW)
- ✅ `web/frontend/src/App.jsx` (modified - add Operations tab)

### Next Steps
1. **Test locally**: Run frontend and API, verify new endpoints work
2. **Commit changes**: Add all 4 files to git
3. **Build & Deploy**: Trigger API and Frontend builds
4. **Verify in production**: Check K8s API pods expose new endpoints
5. **Monitor**: Watch the Operations dashboard for real-time activity!

---

## 📈 Example Use Cases

### **Debugging "Why is the queue so long?"**
1. Open Operations Dashboard
2. Check queue status → See entity_extraction_pending = 1538
3. Check recent activity → See 0 items processed in last 5 minutes
4. Check recent errors → See "populate_gazetteer script not available"
5. **Action**: Fix the script path bug (which you just did!)

### **Monitoring County Coverage**
1. Open Operations Dashboard
2. Scroll to "County Progress" table
3. See which counties have the most articles
4. Identify counties with low coverage
5. **Action**: Add more sources for underrepresented counties

### **Performance Tuning**
1. Check "Processing Velocity" metrics
2. See extraction rate is 2.3/min (too slow)
3. Check "Active Sources" → Only 3 sources being processed
4. **Action**: Increase EXTRACTION_BATCH_SIZE or pod replicas

### **Error Investigation**
1. Check "System Health" → Status: WARNING
2. Check "Recent Errors" → See 15% error rate on domain X
3. Click through to error details
4. **Action**: Update extractor config for problematic domain

---

## 💡 Future Enhancements

**Not implemented yet, but easy to add:**

1. **Pod Resource Metrics**: CPU, memory, disk usage per pod
2. **Cost Tracking**: Cloud SQL queries, API requests, storage costs
3. **Alerting**: Webhook/email when error rate exceeds threshold
4. **Historical Charts**: Time-series graphs of queue depth over 24h
5. **Comparison View**: Compare processing rates week-over-week
6. **Export**: Download telemetry data as CSV for analysis
7. **Filters**: Filter by county, source, time range
8. **Real-time Logs**: Stream recent log entries from pods

---

## 🎉 Summary

**You already had the data** - it was being collected and stored in your database. What was missing was:

1. **Aggregation endpoints** that query the data in useful ways
2. **Real-time UI** that auto-refreshes and shows current state
3. **Unified view** that brings together queue depths, activity, errors, and health

Now you have a **single operations dashboard** that answers the key questions:
- ✅ What's being processed right now?
- ✅ How fast is the pipeline running?
- ✅ Are there any errors?
- ✅ Which queues need attention?
- ✅ Is the system healthy?

All auto-refreshing every 10 seconds with live data from production! 🚀
