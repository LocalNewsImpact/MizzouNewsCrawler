# Work Queue Testing - Quick Reference

## 🚀 Quick Start (5 minutes)

```bash
# Run all tests
./scripts/test-work-queue-all.sh

# Or run individually:
./scripts/test-work-queue-smoke.sh      # Fast (2 min)
./scripts/test-work-queue-full.sh       # Complete (10 min)
```

## 📋 What Gets Tested

### Smoke Test (Fast)
✓ Services start correctly  
✓ Health checks pass  
✓ API endpoints respond  
✓ Unit tests pass  

### Full Integration Test (Comprehensive)
✓ Multi-worker coordination  
✓ Domain partitioning  
✓ Database writes  
✓ No duplicate articles  
✓ Rate limiting  
✓ Fallback mode  
✓ Data integrity  

## 🔍 Manual Verification

```bash
# Start services
docker-compose up -d postgres
docker-compose --profile work-queue up -d work-queue

# Check work queue stats
docker exec mizzou-work-queue curl -s http://localhost:8080/stats | jq

# Check articles in database
docker exec mizzou-postgres psql -U mizzou_user -d mizzou -c \
  "SELECT COUNT(*) FROM articles"

# Check for duplicates (should be 0)
docker exec mizzou-postgres psql -U mizzou_user -d mizzou -c \
  "SELECT candidate_link_id, COUNT(*) FROM articles 
   GROUP BY candidate_link_id HAVING COUNT(*) > 1"
```

## 🐛 Quick Troubleshooting

**Service won't start:**
```bash
docker-compose logs work-queue
docker-compose build work-queue
```

**No articles extracted:**
```bash
# Check candidate_links exist
docker exec mizzou-postgres psql -U mizzou_user -d mizzou -c \
  "SELECT COUNT(*) FROM candidate_links WHERE status='article'"

# Check worker logs
docker-compose logs crawler
```

**Tests failing:**
```bash
# Clean slate
docker-compose down -v
docker system prune -f

# Rebuild and retry
docker-compose build
./scripts/test-work-queue-smoke.sh
```

## ✅ Success Criteria

Before deployment, ensure:
- [ ] All tests pass
- [ ] No duplicate articles
- [ ] Domain diversity > 50%
- [ ] Fallback mode works
- [ ] No errors in logs

## 📖 Full Documentation

See `scripts/TESTING_GUIDE.md` for:
- Detailed test explanations
- Manual testing scenarios
- Database verification queries
- Performance baselines
- Troubleshooting guide
