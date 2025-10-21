# Discovery Pipeline Quick Reference

## 🚀 Quick Start

```bash
# 1. Validate setup
python scripts/validate_discovery_setup.py

# 2. Check status
python -m src.cli discovery-status

# 3. Run discovery
python -m src.cli discover-urls --source-limit 10
```

## 📋 Common Commands

### Discovery Commands

```bash
# Discover from all sources (first run)
python -m src.cli discover-urls

# Discover from specific dataset
python -m src.cli discover-urls --dataset Mizzou-Missouri-State

# Limit number of sources processed
python -m src.cli discover-urls --source-limit 50

# Use scheduling (production)
python -m src.cli discover-urls --due-only

# Override scheduling
python -m src.cli discover-urls --force-all

# Discover from specific source
python -m src.cli discover-urls --source "Source Name"

# Debug mode
python -m src.cli discover-urls --log-level DEBUG --source-limit 5
```

### Status Commands

```bash
# View pipeline status
python -m src.cli discovery-status

# Status for specific dataset
python -m src.cli discovery-status --dataset Mizzou-Missouri-State

# Verbose mode (show source details)
python -m src.cli discovery-status --verbose
```

### Validation

```bash
# Validate entire system
python scripts/validate_discovery_setup.py

# Validate specific dataset
python scripts/validate_discovery_setup.py Mizzou-Missouri-State
```

## 🔍 Troubleshooting

### Problem: "Processing 0 sources"

**Solution**:
```bash
# Check what's due
python -m src.cli discovery-status

# Override scheduling
python -m src.cli discover-urls --force-all
```

### Problem: "Dataset not found"

**Solution**:
```bash
# List available datasets
python -m src.cli discovery-status

# Check database
sqlite3 data/mizzou.db "SELECT label FROM datasets;"
```

### Problem: No URLs discovered

**Solution**:
```bash
# Debug specific source
python -m src.cli discover-urls \
    --source "Source Name" \
    --log-level DEBUG
```

## 📊 Monitoring Queries

```sql
-- Recent discovery activity
SELECT 
    DATE(discovered_at) as date,
    COUNT(*) as urls
FROM candidate_links
WHERE discovered_at >= DATE('now', '-7 days')
GROUP BY DATE(discovered_at);

-- Sources by status
SELECT 
    CASE 
        WHEN MAX(cl.discovered_at) IS NULL THEN 'Never'
        WHEN DATE(MAX(cl.discovered_at)) >= DATE('now', '-1 day') THEN 'Recent'
        ELSE 'Old'
    END as status,
    COUNT(*) as count
FROM sources s
LEFT JOIN candidate_links cl ON s.id = cl.source_host_id
GROUP BY status;
```

## 🎯 Best Practices

### First-Time Setup
1. Run validation: `python scripts/validate_discovery_setup.py`
2. Check status: `python -m src.cli discovery-status`
3. Test with small limit: `python -m src.cli discover-urls --source-limit 5`
4. Verify results: `python -m src.cli discovery-status`

### Production Scheduled Runs
```bash
# Cron job example
0 */6 * * * cd /path/to/repo && python -m src.cli discover-urls --due-only
```

### Debugging
```bash
# Enable debug logging and save to file
python -m src.cli discover-urls \
    --log-level DEBUG \
    --source-limit 5 \
    2>&1 | tee discovery_debug.log
```

## 🆘 Get Help

1. **Check documentation**: `docs/troubleshooting/DISCOVERY_PIPELINE.md`
2. **Run validation**: `python scripts/validate_discovery_setup.py`
3. **Check status**: `python -m src.cli discovery-status`
4. **Enable debug logging**: `--log-level DEBUG`
5. **Review fix summary**: `docs/DISCOVERY_PIPELINE_FIX_SUMMARY.md`

## 📚 Documentation

- **Troubleshooting Guide**: `docs/troubleshooting/DISCOVERY_PIPELINE.md`
- **Fix Summary**: `docs/DISCOVERY_PIPELINE_FIX_SUMMARY.md`
- **Analysis**: `/tmp/pipeline_analysis/DISCOVERY_PIPELINE_ANALYSIS.md`

## ✅ Validation Checklist

Before production deployment:
- [ ] Run `python scripts/validate_discovery_setup.py`
- [ ] Check `python -m src.cli discovery-status`
- [ ] Test `python -m src.cli discover-urls --source-limit 5`
- [ ] Verify logs are clear and actionable
- [ ] Confirm dataset validation works
- [ ] Test with invalid dataset name to see error handling
