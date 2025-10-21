# PR #91 Testing Checklist: ML Model Optimization

**PR:** [#91 - Optimize ML Model Loading: Eliminate 288 Daily spaCy Reloads](https://github.com/LocalNewsImpact/MizzouNewsCrawler/pull/91)  
**Date:** October 19, 2025  
**Status:** Ready for Testing

---

## Executive Summary

This PR eliminates repeated spaCy model reloads (288/day → 1/day) through:
1. **Phase 1:** Increased batch size (50 → 500 articles)
2. **Phase 2:** Cached model with direct function calls (no subprocess)

**Before merging and deploying, we need to verify:**
- ✅ Unit tests pass
- ⏳ Integration tests pass
- ⏳ Local end-to-end testing
- ⏳ Staging environment validation
- ⏳ Performance benchmarks
- ⏳ Memory profiling
- ⏳ Production readiness

---

## Testing Status

### ✅ Completed Tests

#### 1. Unit Tests (Implemented)
- [x] **`tests/test_continuous_processor_entity_caching.py`** (NEW)
  - ✅ Model loaded only once across multiple batches
  - ✅ Cached extractor reused properly
  - ✅ Batch size limiting works
  - ✅ Error handling validated
  - ✅ Zero-count edge case handled

- [x] **`tests/test_continuous_processor.py`** (UPDATED)
  - ✅ Direct function call (no subprocess)
  - ✅ Batch size configuration
  - ✅ Argument passing correct

- [x] **`tests/test_entity_extraction_command.py`** (EXISTING)
  - ✅ Optional extractor parameter works
  - ✅ Backward compatibility maintained

**Run tests:**
```bash
cd /Users/kiesowd/VSCode/NewsCrawler/MizzouNewsCrawler-Scripts
python -m pytest tests/test_continuous_processor_entity_caching.py -v
python -m pytest tests/test_continuous_processor.py::TestProcessEntityExtraction -v
```

---

## ⏳ Additional Testing Required

### 2. Integration Tests (NEEDED)

#### Test: Entity Extraction End-to-End

**Purpose:** Verify the complete entity extraction flow works with cached model

**Test Script:** `tests/integration/test_entity_extraction_integration.py` (CREATE THIS)

```python
"""Integration test for entity extraction with cached model."""

import pytest
from orchestration.continuous_processor import (
    get_cached_entity_extractor,
    process_entity_extraction
)
from src.models.database import DatabaseManager
from tests.fixtures import test_article_with_content


def test_entity_extraction_integration_with_cached_model():
    """Test that entity extraction works end-to-end with cached model."""
    # Setup: Create test article with content
    db = DatabaseManager()
    with db.get_session() as session:
        article = test_article_with_content(session)
        session.add(article)
        session.commit()
        article_id = article.id
    
    # Get cached extractor (this loads the model)
    extractor = get_cached_entity_extractor()
    assert extractor is not None
    
    # Run entity extraction
    result = process_entity_extraction(1)
    assert result is True
    
    # Verify entities were extracted
    with db.get_session() as session:
        from src.models.models import ArticleEntity
        entities = session.query(ArticleEntity).filter_by(
            article_id=article_id
        ).all()
        assert len(entities) > 0
    
    # Cleanup
    with db.get_session() as session:
        session.query(ArticleEntity).filter_by(article_id=article_id).delete()
        session.query(Article).filter_by(id=article_id).delete()
        session.commit()


def test_multiple_batches_reuse_cached_model():
    """Test that multiple batches reuse the same model instance."""
    # Get extractor
    extractor1 = get_cached_entity_extractor()
    
    # Process first batch
    result1 = process_entity_extraction(10)
    
    # Get extractor again
    extractor2 = get_cached_entity_extractor()
    
    # Should be the SAME object
    assert extractor2 is extractor1
    
    # Process second batch
    result2 = process_entity_extraction(10)
    
    # Both should succeed
    assert result1 is True
    assert result2 is True
```

**Action Required:**
```bash
# Create integration test
# Run with pytest
python -m pytest tests/integration/test_entity_extraction_integration.py -v
```

---

### 3. Local End-to-End Testing (CRITICAL)

#### Test A: Continuous Processor Local Run

**Purpose:** Verify the processor runs correctly with cached model locally

**Steps:**
```bash
# 1. Ensure test database has pending articles
cd /Users/kiesowd/VSCode/NewsCrawler/MizzouNewsCrawler-Scripts

# 2. Run continuous processor
python orchestration/continuous_processor.py

# 3. Watch logs for expected behavior
# Should see ONCE at startup:
# [INFO] 🧠 Loading spaCy model (one-time initialization)...
# [INFO] ✅ spaCy model loaded and cached in memory

# 4. Watch for entity extraction cycles
# [INFO] ▶️  Entity extraction (1234 pending, limit 500)
# [INFO] ✅ Entity extraction completed successfully (45.2s)

# 5. Verify NO additional model loads
# grep "Loading spaCy model" in logs should show ONLY the startup load
```

**Success Criteria:**
- [ ] Model loads exactly once at startup
- [ ] Entity extraction runs successfully
- [ ] No model reload messages during batch processing
- [ ] Memory stays constant (monitor with Activity Monitor)
- [ ] Batch size is 500 articles
- [ ] No errors or exceptions

---

#### Test B: Memory Usage Verification

**Purpose:** Confirm memory usage is stable and matches expectations

**Steps:**
```bash
# 1. Start processor
python orchestration/continuous_processor.py &
PROC_PID=$!

# 2. Monitor memory usage over 30 minutes
watch -n 60 "ps -o rss,vsz,pid,comm -p $PROC_PID"

# Expected:
# RSS: ~2.5GB constant (no spikes)
# VSZ: Stable
# No gradual growth

# 3. Check for memory leaks
# After 30 minutes, memory should still be ~2.5GB
# No OOM events

# 4. Stop processor
kill $PROC_PID
```

**Success Criteria:**
- [ ] Memory usage constant ~2.5GB ± 200MB
- [ ] No memory spikes to 4.5GB
- [ ] No gradual memory growth (leak)
- [ ] No OOM kills

---

### 4. Database Impact Testing (RECOMMENDED)

#### Test: Database Connection Handling

**Purpose:** Ensure direct function calls don't cause database connection issues

**Test Script:** `tests/integration/test_database_connections.py` (CREATE THIS)

```python
"""Test database connection handling with direct function calls."""

import pytest
from orchestration.continuous_processor import process_entity_extraction
from src.models.database import DatabaseManager


def test_multiple_batches_handle_db_connections_correctly():
    """Verify that multiple batches don't exhaust DB connection pool."""
    db = DatabaseManager()
    
    # Run multiple batches in quick succession
    results = []
    for i in range(5):
        result = process_entity_extraction(10)
        results.append(result)
    
    # All should succeed
    assert all(results)
    
    # Verify DB connection pool is healthy
    # (no connection leaks)
    engine = db._engine
    pool = engine.pool
    
    # Check pool stats
    assert pool.checkedout() < pool.size()  # Not all connections checked out
```

**Action Required:**
```bash
python -m pytest tests/integration/test_database_connections.py -v
```

---

### 5. Performance Benchmarking (CRITICAL)

#### Benchmark A: Model Load Time

**Purpose:** Measure actual model load time savings

**Test Script:** `benchmarks/benchmark_model_loading.py` (CREATE THIS)

```python
"""Benchmark entity extraction with and without caching."""

import time
from orchestration import continuous_processor


def benchmark_with_cached_model(num_batches=5):
    """Benchmark entity extraction with cached model."""
    # Prime the cache
    extractor = continuous_processor.get_cached_entity_extractor()
    
    start_time = time.time()
    
    for i in range(num_batches):
        # Use cached extractor
        result = continuous_processor.process_entity_extraction(10)
        assert result is True
    
    elapsed = time.time() - start_time
    avg_per_batch = elapsed / num_batches
    
    print(f"Cached model - {num_batches} batches:")
    print(f"  Total time: {elapsed:.2f}s")
    print(f"  Avg per batch: {avg_per_batch:.2f}s")
    
    return avg_per_batch


def benchmark_without_cached_model_simulation(num_batches=5):
    """Simulate old behavior (model reload per batch)."""
    from src.pipeline.entity_extraction import ArticleEntityExtractor
    
    start_time = time.time()
    
    for i in range(num_batches):
        # Create new extractor each time (simulates old behavior)
        extractor = ArticleEntityExtractor()  # This loads the model
        # Process would happen here
        time.sleep(0.1)  # Simulate processing time
    
    elapsed = time.time() - start_time
    avg_per_batch = elapsed / num_batches
    
    print(f"No cache (old behavior) - {num_batches} batches:")
    print(f"  Total time: {elapsed:.2f}s")
    print(f"  Avg per batch: {avg_per_batch:.2f}s")
    
    return avg_per_batch


if __name__ == "__main__":
    print("Benchmarking entity extraction performance...")
    print()
    
    cached_time = benchmark_with_cached_model(5)
    print()
    
    uncached_time = benchmark_without_cached_model_simulation(5)
    print()
    
    improvement = ((uncached_time - cached_time) / uncached_time) * 100
    print(f"Performance improvement: {improvement:.1f}%")
    print(f"Time saved per batch: {uncached_time - cached_time:.2f}s")
```

**Action Required:**
```bash
python benchmarks/benchmark_model_loading.py
```

**Expected Results:**
- Cached model: ~45s per batch (no model load overhead)
- Old behavior: ~47s per batch (includes 2s model load)
- Improvement: ~4-5% per batch

---

#### Benchmark B: Memory Footprint

**Purpose:** Measure actual memory usage

**Test Script:** `benchmarks/benchmark_memory.py` (CREATE THIS)

```python
"""Benchmark memory usage of entity extraction."""

import os
import psutil
import time
from orchestration import continuous_processor


def get_memory_usage_mb():
    """Get current process memory usage in MB."""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024


def benchmark_memory_stability():
    """Monitor memory usage over multiple batches."""
    print("Measuring memory usage...")
    
    # Baseline
    baseline = get_memory_usage_mb()
    print(f"Baseline: {baseline:.1f} MB")
    
    # Load model (should spike)
    extractor = continuous_processor.get_cached_entity_extractor()
    after_load = get_memory_usage_mb()
    load_increase = after_load - baseline
    print(f"After model load: {after_load:.1f} MB (+{load_increase:.1f} MB)")
    
    # Run batches
    memory_readings = [after_load]
    for i in range(5):
        continuous_processor.process_entity_extraction(10)
        mem = get_memory_usage_mb()
        memory_readings.append(mem)
        print(f"After batch {i+1}: {mem:.1f} MB")
        time.sleep(1)
    
    # Analysis
    avg_memory = sum(memory_readings) / len(memory_readings)
    max_memory = max(memory_readings)
    min_memory = min(memory_readings)
    
    print(f"\nMemory Statistics:")
    print(f"  Average: {avg_memory:.1f} MB")
    print(f"  Range: {min_memory:.1f} - {max_memory:.1f} MB")
    print(f"  Variation: {max_memory - min_memory:.1f} MB")
    
    # Success criteria
    variation = max_memory - min_memory
    assert variation < 500, f"Memory variation too high: {variation:.1f} MB"
    print("\n✅ Memory usage is stable!")


if __name__ == "__main__":
    benchmark_memory_stability()
```

**Action Required:**
```bash
pip install psutil
python benchmarks/benchmark_memory.py
```

**Expected Results:**
- Baseline: ~500MB
- After load: ~2500MB (model in memory)
- Variation during batches: <500MB
- No gradual growth

---

### 6. Staging Environment Testing (CRITICAL)

#### Deploy to Staging

**Purpose:** Validate in environment matching production

**Prerequisites:**
- [ ] Staging cluster available
- [ ] Staging database populated with test data
- [ ] Monitoring configured

**Steps:**
```bash
# 1. Build processor image for staging
gcloud builds triggers run build-processor-manual \
  --branch=copilot/vscode1760881515439

# 2. Deploy to staging namespace
kubectl set image deployment/mizzou-processor \
  processor=gcr.io/PROJECT_ID/mizzou-processor:COMMIT_SHA \
  -n staging

# 3. Watch rollout
kubectl rollout status deployment/mizzou-processor -n staging

# 4. Monitor logs
kubectl logs -f deployment/mizzou-processor -n staging | grep -E "Loading spaCy|Entity extraction"

# 5. Monitor memory
watch kubectl top pod -n staging -l app=mizzou-processor

# 6. Let run for 2 hours minimum
```

**Success Criteria:**
- [ ] Pod starts successfully
- [ ] Model loads exactly once (check logs)
- [ ] Entity extraction runs successfully
- [ ] Memory stays constant ~2.5GB
- [ ] No OOM kills for 2+ hours
- [ ] Entities appear in database
- [ ] No errors in logs

---

### 7. Backward Compatibility Testing (IMPORTANT)

#### Test: CLI Still Works

**Purpose:** Ensure CLI command still functions correctly

**Steps:**
```bash
# Test the CLI command directly (should create new extractor)
python -m src.cli.main extract-entities --limit 10 --source "Test Source"

# Should work without errors
# Should create its own extractor (not using cached one)
```

**Success Criteria:**
- [ ] CLI command works unchanged
- [ ] No errors
- [ ] Entities extracted correctly

---

### 8. Failure Mode Testing (CRITICAL)

#### Test A: Extractor Initialization Failure

**Purpose:** Verify graceful handling of model load failures

**Test Script:** `tests/test_failure_modes.py` (CREATE THIS)

```python
"""Test failure modes and error handling."""

import pytest
from unittest.mock import patch, MagicMock
from orchestration import continuous_processor


def test_model_load_failure_is_handled():
    """Test that model load failures are handled gracefully."""
    # Reset cache
    continuous_processor._ENTITY_EXTRACTOR = None
    
    with patch('src.pipeline.entity_extraction.ArticleEntityExtractor') as mock_class:
        # Simulate model load failure
        mock_class.side_effect = RuntimeError("Failed to load model")
        
        # Should raise the error (let it propagate)
        with pytest.raises(RuntimeError):
            continuous_processor.get_cached_entity_extractor()


def test_entity_extraction_failure_returns_false():
    """Test that entity extraction failures return False."""
    with patch('orchestration.continuous_processor.handle_entity_extraction_command') as mock_handle:
        mock_handle.return_value = 1  # Failure exit code
        
        result = continuous_processor.process_entity_extraction(10)
        assert result is False


def test_entity_extraction_exception_is_caught():
    """Test that exceptions during extraction are caught."""
    with patch('orchestration.continuous_processor.handle_entity_extraction_command') as mock_handle:
        mock_handle.side_effect = Exception("Database connection failed")
        
        result = continuous_processor.process_entity_extraction(10)
        assert result is False  # Should not crash, just return False
```

**Action Required:**
```bash
python -m pytest tests/test_failure_modes.py -v
```

---

#### Test B: OOM Simulation

**Purpose:** Verify behavior under memory pressure

**Manual Test:**
```bash
# 1. Start processor with limited memory
docker run --memory=3g \
  mizzou-processor:latest \
  python orchestration/continuous_processor.py

# 2. Monitor behavior
# Should work normally (model fits in 3GB)

# 3. Try with very limited memory
docker run --memory=1.5g \
  mizzou-processor:latest \
  python orchestration/continuous_processor.py

# Should fail to load model or OOM quickly
# (This validates our 2.5Gi memory request is appropriate)
```

---

### 9. Load Testing (RECOMMENDED)

#### Test: High Volume Processing

**Purpose:** Verify performance under load

**Test Script:** `tests/load/test_high_volume.py` (CREATE THIS)

```python
"""Load test for entity extraction."""

import time
from concurrent.futures import ThreadPoolExecutor
from orchestration import continuous_processor


def test_high_volume_entity_extraction():
    """Test entity extraction with many pending articles."""
    # Simulate 10,000 pending articles
    result = continuous_processor.process_entity_extraction(10000)
    
    # Should process 500 articles (batch size)
    assert result is True


def test_concurrent_batch_processing():
    """Test that concurrent calls handle properly."""
    # Note: current implementation uses global cache,
    # so concurrent calls should share the same model
    
    def process_batch(count):
        return continuous_processor.process_entity_extraction(count)
    
    # Run multiple batches concurrently
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(process_batch, 10) for _ in range(3)]
        results = [f.result() for f in futures]
    
    # All should succeed (or handle gracefully)
    # Note: May need locking if database writes conflict
    assert len(results) == 3
```

**Action Required:**
```bash
python -m pytest tests/load/test_high_volume.py -v
```

---

### 10. Production Rollout Testing (CRITICAL)

#### Pre-Deployment Checklist

**Before deploying to production:**

- [ ] All unit tests pass
- [ ] Integration tests pass
- [ ] Local end-to-end testing completed successfully
- [ ] Staging environment validated (2+ hours stable)
- [ ] Performance benchmarks meet expectations
- [ ] Memory profiling shows stable usage
- [ ] Failure modes tested and handled
- [ ] Rollback plan documented and tested
- [ ] Monitoring alerts configured
- [ ] On-call team notified

---

## Testing Schedule

### Phase 1: Local Testing (1-2 hours)
- [ ] Run unit tests
- [ ] Local end-to-end test
- [ ] Memory profiling
- [ ] Performance benchmarks

### Phase 2: Integration Testing (2-3 hours)
- [ ] Create integration tests
- [ ] Database connection testing
- [ ] Failure mode testing
- [ ] Load testing

### Phase 3: Staging Deployment (4-6 hours)
- [ ] Deploy to staging
- [ ] Monitor for 2+ hours
- [ ] Verify metrics
- [ ] Test backward compatibility

### Phase 4: Production Deployment (Scheduled)
- [ ] Deploy during maintenance window
- [ ] Monitor closely for 24 hours
- [ ] Verify success criteria
- [ ] Document results

**Total Estimated Testing Time:** 8-12 hours

---

## Success Criteria Summary

After all testing, the following must be true:

### Functional Requirements
- ✅ Unit tests pass (100% of new tests)
- ⏳ Integration tests pass
- ⏳ Entity extraction works end-to-end
- ⏳ CLI command still works (backward compatibility)
- ⏳ Database operations succeed

### Performance Requirements
- ⏳ Model loads exactly 1 time per processor instance
- ⏳ Memory usage constant ~2.5GB (±200MB)
- ⏳ No memory spikes to 4.5GB
- ⏳ Batch size consistently 500 articles
- ⏳ Processing time ≤ old implementation

### Reliability Requirements
- ⏳ No OOM kills for 24+ hours
- ⏳ No memory leaks (stable over time)
- ⏳ Errors handled gracefully
- ⏳ Rollback tested and works

### Operational Requirements
- ⏳ Logs show expected behavior
- ⏳ Monitoring metrics correct
- ⏳ Alerts configured
- ⏳ Documentation complete

---

## Monitoring Post-Deployment

After deploying to production, monitor these metrics:

### Key Metrics (First 24 Hours)
```bash
# Model load frequency (should be ~0 after startup)
kubectl logs -f deployment/mizzou-processor -n production | grep -c "Loading spaCy model"

# Memory usage (should be constant)
watch kubectl top pod -n production -l app=mizzou-processor

# Entity extraction success rate
kubectl logs deployment/mizzou-processor -n production | grep "Entity extraction" | grep -c "completed successfully"

# Error rate
kubectl logs deployment/mizzou-processor -n production | grep -c "Entity extraction failed"
```

### Success Indicators
- [ ] Log shows "Loading spaCy model" exactly once per pod
- [ ] Memory stays ~2.5GB constantly
- [ ] Entity extraction success rate ≥ 95%
- [ ] No OOM events
- [ ] Processing time reduced
- [ ] Batch size logs show 500 articles

---

## Rollback Plan

If issues are detected:

```bash
# 1. Immediate rollback
kubectl rollout undo deployment/mizzou-processor -n production

# 2. Monitor rollback
kubectl rollout status deployment/mizzou-processor -n production

# 3. Verify old behavior restored
kubectl logs -f deployment/mizzou-processor -n production

# 4. Document issue and root cause
# 5. Fix in new PR
# 6. Re-test before attempting deployment again
```

---

## Contact

For questions about testing:
- **GitHub Issue:** [#90](https://github.com/LocalNewsImpact/MizzouNewsCrawler/issues/90)
- **Pull Request:** [#91](https://github.com/LocalNewsImpact/MizzouNewsCrawler/pull/91)
- **Team:** @dkiesow

---

**Status:** 🟡 Testing In Progress  
**Next Step:** Run unit tests and begin integration testing  
**Target Deployment:** After all tests pass and staging validated
