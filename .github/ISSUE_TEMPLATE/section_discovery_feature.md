# Adaptive Section Discovery for Enhanced News URL Coverage

## Problem Statement

**Current Limitation**: When RSS feeds are unavailable or fail, the discovery system only checks the homepage for article links. This results in missing many stories that are only published on section pages (e.g., `/news`, `/local`, `/sports`, `/weather`).

**Real-World Impact**: Sites like KRCG and other local news outlets often organize content into sections, with new stories appearing on section pages before (or instead of) the homepage. Our current homepage-only approach means we're missing significant coverage.

## Proposed Solution

Implement an **adaptive section discovery system** that:
1. Automatically discovers section URLs during successful RSS/homepage discovery
2. Stores discovered sections in source metadata
3. Checks these sections when RSS is unavailable
4. Continuously refines the section list based on success metrics

## Architecture

### Phase 1: Section Detection & Storage

```python
# New method in NewsDiscovery class
def _discover_section_urls(
    self,
    source_url: str,
    html: str,
) -> list[str]:
    """
    Detect common section pages from navigation elements.
    
    Strategy:
    1. Find <nav>, <menu>, or elements with nav-related classes
    2. Extract links matching patterns: /news, /local, /sports, etc.
    3. Filter to same-domain, non-feed URLs
    4. Return list of candidate section URLs
    """
```

**Storage Schema**:
```json
{
  "discovered_sections": [
    {
      "url": "/news",
      "discovered_at": "2025-11-16T10:00:00Z",
      "last_successful": "2025-11-16T10:00:00Z",
      "success_count": 45,
      "failure_count": 2,
      "avg_articles_found": 12.3
    }
  ],
  "section_discovery_enabled": true,
  "section_last_updated": "2025-11-16T10:00:00Z"
}
```

### Phase 2: Section Utilization

```python
# Enhanced discover_with_newspaper4k
def discover_with_newspaper4k(
    self,
    source_url: str,
    source_id: str | None = None,
    operation_id: str | None = None,
    source_meta: dict | None = None,
    allow_build: bool = True,
    rss_already_attempted: bool = False,
) -> list[dict]:
    # ... existing RSS/homepage logic ...
    
    # NEW: Check proven sections when RSS fails
    if not rss_results and source_meta:
        sections = self._get_proven_sections(source_meta)
        if sections:
            logger.info(f"Checking {len(sections)} proven sections")
            section_candidates = self._check_section_pages(
                source_url,
                sections,
                source_meta,
            )
            if section_candidates:
                return section_candidates
```

### Phase 3: Section Performance Tracking

```python
def _update_section_performance(
    self,
    source_id: str,
    section_url: str,
    success: bool,
    articles_found: int,
) -> None:
    """
    Track section performance metrics:
    - Success/failure counts
    - Average articles found
    - Last successful discovery time
    - Automatic pruning of low-performing sections
    """
```

## Implementation Plan

### Stage 1: Detection Infrastructure (Week 1)
- [ ] Add `_discover_section_urls()` method
- [ ] Implement navigation parsing logic
- [ ] Add section URL normalization
- [ ] Create unit tests for section detection

**Success Criteria**: Can reliably extract 3-5 section URLs from typical news sites

### Stage 2: Storage & Retrieval (Week 1-2)
- [ ] Define section metadata schema
- [ ] Add `_store_discovered_sections()` method
- [ ] Add `_get_proven_sections()` method
- [ ] Add database migration for new metadata fields (if needed)
- [ ] Create integration tests for storage/retrieval

**Success Criteria**: Can persist and retrieve section data across discovery runs

### Stage 3: Section Checking (Week 2)
- [ ] Add `_check_section_pages()` method
- [ ] Implement parallel section fetching (respect rate limits)
- [ ] Add deduplication across homepage + section results
- [ ] Add telemetry for section-based discovery
- [ ] Create integration tests for section checking

**Success Criteria**: Can fetch articles from sections with proper deduplication

### Stage 4: Performance Tracking (Week 3)
- [ ] Add `_update_section_performance()` method
- [ ] Implement success/failure tracking
- [ ] Add automatic section pruning (remove low performers)
- [ ] Add section quality scoring
- [ ] Create tests for performance tracking

**Success Criteria**: System automatically removes ineffective sections

### Stage 5: Telemetry & Monitoring (Week 3-4)
- [ ] Add section discovery to telemetry schema
- [ ] Track discovery method: `section_page` vs `homepage`
- [ ] Add Grafana dashboards for section metrics
- [ ] Add CLI command to view/manage sections
- [ ] Create end-to-end tests

**Success Criteria**: Full visibility into section discovery effectiveness

## Testing Strategy

### Unit Tests
```python
class TestSectionDiscovery:
    def test_extract_nav_sections(self):
        """Test section extraction from navigation HTML"""
        
    def test_section_url_normalization(self):
        """Test relative/absolute URL handling"""
        
    def test_section_deduplication(self):
        """Test removing duplicate sections"""
        
    def test_proven_section_filtering(self):
        """Test filtering by success metrics"""
```

### Integration Tests
```python
class TestSectionDiscoveryIntegration:
    def test_section_storage_and_retrieval(self):
        """Test full storage cycle"""
        
    def test_section_performance_tracking(self):
        """Test metrics update correctly"""
        
    def test_section_automatic_pruning(self):
        """Test low performers are removed"""
```

### End-to-End Tests
```python
def test_krcg_section_discovery():
    """Test on real KRCG site (if accessible)"""
    
def test_multi_section_discovery():
    """Test discovering from multiple sections"""
    
def test_rss_fallback_to_sections():
    """Test fallback behavior when RSS fails"""
```

## Configuration

### Source-Level Configuration
```python
# In source metadata
{
    "section_discovery_enabled": true,
    "section_discovery_max_sections": 5,  # Don't check too many
    "section_discovery_min_success_rate": 0.3,  # Prune below 30%
    "section_check_strategy": "proven",  # or "all", "top_n"
}
```

### Global Configuration
```python
# In config.py or environment
SECTION_DISCOVERY_ENABLED = True
SECTION_MAX_CONCURRENT_CHECKS = 3  # Respect rate limits
SECTION_MIN_ARTICLES_THRESHOLD = 5  # Must find at least N articles
SECTION_PRUNE_AFTER_FAILURES = 5  # Remove after N consecutive failures
```

## Success Metrics

### Phase 1 (Detection)
- Successfully extract sections from 80%+ of test sites
- False positive rate < 10%

### Phase 2 (Utilization)
- Increase article discovery by 25%+ on non-RSS sites
- No impact on RSS-enabled sites (no slowdown)

### Phase 3 (Optimization)
- Section performance tracking reduces wasted requests by 40%
- Automatic pruning maintains < 5 sections per source on average

## Rollout Strategy

### Phase 1: Opt-in Beta (Weeks 1-2)
- Enable only for manually flagged sources
- Monitor performance closely
- Gather metrics on effectiveness

### Phase 2: Gradual Rollout (Weeks 3-4)
- Enable for all non-RSS sources with 0-5 sections
- Monitor error rates and performance
- Adjust thresholds based on data

### Phase 3: Full Deployment (Week 5+)
- Enable globally with automatic section discovery
- Continuous monitoring and optimization

## Risk Assessment

### Technical Risks
1. **Performance Impact**: Checking multiple sections increases request count
   - Mitigation: Parallel fetching with rate limiting, automatic pruning
   
2. **False Positives**: Detecting wrong URLs as sections
   - Mitigation: Performance tracking removes ineffective sections automatically
   
3. **Maintenance Burden**: Sites change navigation structure
   - Mitigation: Automatic re-discovery on each run updates section list

### Operational Risks
1. **Rate Limiting**: More requests might trigger blocks
   - Mitigation: Respect existing rate limits, add per-source delays
   
2. **Storage Growth**: Section metadata increases DB size
   - Mitigation: Automatic pruning, limit to top N sections per source

## Alternative Approaches Considered

### 1. Manual Configuration
**Rejected**: Doesn't scale to 100+ sources, requires constant maintenance

### 2. Hardcoded Patterns
**Rejected**: Different sites use different URL structures (/news vs /local-news vs /latest)

### 3. ML-Based Section Detection
**Deferred**: Current heuristic approach is simpler and likely sufficient

## Open Questions

1. Should we check sections in parallel or sequentially?
   - **Recommendation**: Parallel with max 3 concurrent, respects rate limits better
   
2. How often should we re-discover sections?
   - **Recommendation**: Every 7 days or on 3 consecutive RSS failures
   
3. Should sections be shared across sources on same domain?
   - **Recommendation**: No, each source independent for now (simpler)

## Documentation Requirements

- [ ] Update discovery pipeline architecture docs
- [ ] Add section discovery to README
- [ ] Create operator guide for managing sections
- [ ] Add troubleshooting guide for section-related issues
- [ ] Update telemetry documentation

## Related Issues

- #XXX: RSS failure handling improvements
- #XXX: Discovery performance optimization
- #XXX: Adaptive crawling strategy

## References

- Current discovery code: `src/crawler/discovery.py`
- Telemetry schema: `src/telemetry/store.py`
- Source model: `src/models/__init__.py`
