# Adaptive Section Discovery

## Overview

The Adaptive Section Discovery feature enhances news URL coverage by automatically detecting and storing section URLs (e.g., `/news`, `/local`, `/sports`) from news websites. This addresses the limitation where RSS-only discovery misses articles published exclusively on section pages.

## Phase 1: Detection & Storage (Implemented)

### Database Schema

Three new columns added to the `sources` table:

```sql
discovered_sections JSONB       -- Stores discovered section URLs with metrics
section_discovery_enabled BOOLEAN  -- Flag to enable/disable per source (default: TRUE)
section_last_updated TIMESTAMP     -- Last update timestamp
```

### Section Detection Logic

The `_discover_section_urls()` method:
1. Searches for navigation elements (`<nav>`, `<menu>`, `<header>`, or divs with nav-related classes)
2. Extracts links matching common section patterns
3. Filters to same-domain, non-feed URLs
4. Returns normalized list of section URLs

### Supported Section Patterns

- `/news` - General news section
- `/local` - Local news coverage
- `/sports` - Sports section
- `/weather` - Weather updates
- `/politics` - Political news
- `/business` - Business section
- `/entertainment` - Entertainment news
- `/opinion` - Opinion pieces
- `/lifestyle` - Lifestyle content
- `/community` - Community news

### Features

**Smart Filtering:**
- Excludes RSS/feed URLs (`/feed`, `/rss`, `.xml`)
- Enforces same-domain only (no external links)
- Skips non-HTTP protocols (`mailto:`, `tel:`, `javascript:`)
- Deduplicates URLs
- Strips query parameters and fragments

**Limits:**
- Maximum 10 sections per source
- Case-insensitive pattern matching
- Normalized URLs for consistency

## Usage

### Running the Migration

```bash
python scripts/migrations/add_section_discovery_columns.py
```

The migration:
- Checks if columns already exist (safe to run multiple times)
- Supports both PostgreSQL (JSONB) and SQLite (TEXT/JSON)
- Preserves existing data

### Detecting Sections

```python
from src.crawler.discovery import NewsDiscovery

# Discover sections from HTML
sections = NewsDiscovery._discover_section_urls(
    source_url="https://example.com",
    html=homepage_html
)

# Returns: ["https://example.com/news", "https://example.com/local", ...]
```

### Storing Section Data

```python
import json
from datetime import datetime
from sqlalchemy import text

# Example section data structure
sections = [
    {
        "url": "/news",
        "discovered_at": datetime.utcnow().isoformat(),
        "last_successful": datetime.utcnow().isoformat(),
        "success_count": 10,
        "failure_count": 1,
        "avg_articles_found": 15.5,
    }
]

# Store in database (PostgreSQL)
conn.execute(
    text("""
        UPDATE sources 
        SET discovered_sections = :sections::jsonb,
            section_last_updated = :updated
        WHERE id = :id
    """),
    {
        "sections": json.dumps(sections),
        "updated": datetime.utcnow(),
        "id": source_id,
    }
)
```

### Querying Section Data

```python
# Retrieve sections for a source
result = conn.execute(
    text("SELECT discovered_sections FROM sources WHERE id = :id"),
    {"id": source_id}
).fetchone()

sections = result[0]
if isinstance(sections, str):
    sections = json.loads(sections)
```

## Testing

### Unit Tests

Located in `tests/crawler/test_section_discovery.py` (16 tests):
- Empty HTML handling
- Basic section detection
- Relative path resolution
- RSS/feed filtering
- Same-domain enforcement
- Deduplication
- Result limiting
- Case-insensitive matching
- Non-HTTP protocol filtering
- Query parameter stripping
- Real-world examples

### Integration Tests

Located in `tests/integration/test_section_storage.py` (6 tests):
- Column existence verification
- Section data storage
- Section data retrieval
- Enabled/disabled flag toggling
- NULL section handling
- Update operations

### Running Tests

```bash
# Run all section discovery tests
pytest tests/crawler/test_section_discovery.py tests/integration/test_section_storage.py -v

# Run only unit tests
pytest tests/crawler/test_section_discovery.py -v

# Run only integration tests  
pytest tests/integration/test_section_storage.py -v
```

## Implementation Notes

### Design Decisions

1. **Database Columns vs. Metadata JSON**: Per issue guidance, section data is stored in dedicated columns rather than in the `metadata` JSON field for better type safety and query performance.

2. **Static Method**: `_discover_section_urls()` is a static method since it doesn't require instance state, making it easier to test and reuse.

3. **JSON Storage**: Section data is stored as JSON to allow flexible schema evolution for performance metrics (success_count, failure_count, avg_articles_found, etc.).

4. **Enabled by Default**: The `section_discovery_enabled` flag defaults to TRUE to enable the feature for all sources unless explicitly disabled.

### Future Enhancements (Phase 2+)

Phase 1 implements detection and storage only. Future phases will:
- **Phase 2**: Utilize sections when RSS is unavailable in `discover_with_newspaper4k()`
- **Phase 3**: Track section performance metrics (success/failure rates)
- **Phase 4**: Implement automatic pruning of low-performing sections
- **Phase 5**: Add telemetry and monitoring dashboards

## Troubleshooting

### Migration Issues

**Problem**: Migration fails with "column already exists"  
**Solution**: The migration checks for existing columns - this is safe to ignore.

**Problem**: NOT NULL constraint failed  
**Solution**: Ensure you're including all required columns (`rss_consecutive_failures`, `rss_transient_failures`, `no_effective_methods_consecutive`) in INSERT statements.

### Section Detection Issues

**Problem**: No sections detected from HTML  
**Solution**: Verify the HTML contains navigation elements with links matching the section patterns.

**Problem**: Too many/few sections detected  
**Solution**: Adjust section patterns or max limit (currently 10) in `_discover_section_urls()`.

## References

- Issue: [Implement Adaptive Section Discovery for Enhanced News Coverage]
- Source Model: `src/models/__init__.py` (class `Source`)
- Discovery Module: `src/crawler/discovery.py` (class `NewsDiscovery`)
- Migration Script: `scripts/migrations/add_section_discovery_columns.py`
