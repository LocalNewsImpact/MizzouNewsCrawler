# Discovery Pipeline Improvements (October 2025)

## What's New

The discovery pipeline has been significantly enhanced with:

✅ **Database Compatibility** - Works seamlessly on SQLite (default) and PostgreSQL  
✅ **User-Friendly Defaults** - First run works out of the box  
✅ **Clear Error Messages** - Dataset validation with helpful suggestions  
✅ **Enhanced Visibility** - New `discovery-status` command for pipeline inspection  
✅ **Pre-flight Validation** - Catch issues before running discovery  
✅ **Comprehensive Documentation** - Complete troubleshooting guide  
✅ **Robust Test Coverage** - Tests for SQLite compatibility and CLI behavior

## Quick Start

### 1. Validate Your Setup

Before running discovery for the first time:

```bash
python scripts/validate_discovery_setup.py
```

Expected output:
```
✅ All pre-flight checks passed - ready for discovery!
```

### 2. Check Pipeline Status

View the current state of your discovery pipeline:

```bash
python -m src.cli discovery-status
```

This shows:
- Available datasets
- Total sources and their discovery status
- Sources due for discovery
- Recent discovery activity

### 3. Run Discovery

**First run (discover from all sources)**:
```bash
python -m src.cli discover-urls --source-limit 10
```

**For specific dataset**:
```bash
python -m src.cli discover-urls --dataset Mizzou-Missouri-State
```

**Production scheduled runs** (uses scheduling logic):
```bash
python -m src.cli discover-urls --due-only
```

## Common Issues Resolved

### Issue: "Processing 0 sources"

**Before**: No explanation, just zero results  
**Now**: Clear warning about scheduling behavior with suggestions

```bash
# Check what's happening
python -m src.cli discovery-status

# Override scheduling if needed
python -m src.cli discover-urls --force-all
```

### Issue: "Dataset not found"

**Before**: Silent failure  
**Now**: Clear error with available datasets listed

```
❌ Dataset 'InvalidName' not found in database
ℹ️  Available datasets: Mizzou-Missouri-State, Other-Dataset
```

### Issue: Database compatibility errors

**Before**: PostgreSQL-specific SQL failed on SQLite  
**Now**: Automatic dialect detection and query adaptation

## New Commands

### `discovery-status` - Pipeline Visibility

```bash
# View overall status
python -m src.cli discovery-status

# Status for specific dataset
python -m src.cli discovery-status --dataset Mizzou-Missouri-State

# Verbose mode with source details
python -m src.cli discovery-status --verbose
```

### Validation Script

```bash
# Validate entire system
python scripts/validate_discovery_setup.py

# Validate specific dataset
python scripts/validate_discovery_setup.py Mizzou-Missouri-State
```

## Documentation

Comprehensive documentation has been added:

- **[Quick Reference](docs/DISCOVERY_QUICK_REFERENCE.md)** - Common commands and troubleshooting
- **[Troubleshooting Guide](docs/troubleshooting/DISCOVERY_PIPELINE.md)** - Detailed diagnostic procedures
- **[Fix Summary](docs/DISCOVERY_PIPELINE_FIX_SUMMARY.md)** - Complete overview of improvements

## Migration Notes

### Changed Defaults

The `--due-only` flag now defaults to `False` instead of `True`:

```bash
# OLD behavior (implicit scheduling)
python -m src.cli discover-urls
# Would skip sources not due

# NEW behavior (no scheduling by default)
python -m src.cli discover-urls
# Discovers from all sources

# To use scheduling explicitly
python -m src.cli discover-urls --due-only
```

**Impact**: First-time users will see sources discovered immediately. Production workflows should add `--due-only` explicitly to maintain scheduling behavior.

### For Existing Cron Jobs

Update scheduled jobs to explicitly use `--due-only`:

```bash
# Update your crontab
0 */6 * * * cd /path/to/repo && python -m src.cli discover-urls --due-only
```

## Technical Details

### Database Compatibility

The pipeline now automatically detects the database type and uses appropriate SQL syntax:

- **PostgreSQL**: Uses `DISTINCT ON` for efficient deduplication
- **SQLite**: Uses `GROUP BY` for compatibility

No configuration needed - works based on your database connection string.

### Error Handling

Enhanced error handling provides:
- Dataset validation before query execution
- Clear error messages with actionable suggestions
- Debug logging shows skip reasons for filtered sources
- Validation script catches issues early

## Testing

New test suites ensure reliability:

```bash
# Test SQLite compatibility
pytest tests/crawler/test_discovery_sqlite_compat.py -v

# Test CLI defaults
pytest tests/cli/test_discovery_cli_defaults.py -v
```

## Getting Help

If you encounter issues:

1. **Run validation**: `python scripts/validate_discovery_setup.py`
2. **Check status**: `python -m src.cli discovery-status`
3. **Enable debug logging**: `python -m src.cli discover-urls --log-level DEBUG`
4. **Review documentation**: `docs/troubleshooting/DISCOVERY_PIPELINE.md`

---

**For more details, see**: [Discovery Pipeline Fix Summary](docs/DISCOVERY_PIPELINE_FIX_SUMMARY.md)
