# Documentation Index

This directory contains all project documentation organized by category.

## 📂 Directory Structure

### `/deployment/`
Documentation related to infrastructure deployment, Cloud SQL, Kubernetes, and GCP services.

**Key files:**
- Cloud SQL migration documentation
- Kubernetes deployment guides
- Argo Workflows documentation
- Cluster scaling and capacity planning
- BigQuery and Datastream setup

### `/features/`
Documentation for implemented features and capabilities.

**Key files:**
- Bot detection and blocking systems
- Proxy integration (Decodo)
- Custom source lists
- Telemetry systems
- Origin proxy configuration
- Rate limiting implementations

### `/troubleshooting/`
Bug fixes, issue resolutions, and troubleshooting guides.

**Key files:**
- Performance issues and fixes
- Chrome/Selenium configuration issues
- Dataset and data cleaning problems
- Entity extraction performance
- Memory and resource issues
- URL filtering updates

### `/status/`
Status reports, summaries, and completion documentation.

**Key files:**
- Migration status reports
- Feature completion summaries
- API migration status
- Deployment verification results

### `/archive/`
Historical documentation, planning docs, and completed work.

**Key files:**
- Branch management and cleanup
- Issue tracking (Issues #16-24, etc.)
- PR reviews and conflict resolutions
- Phase tracking and metrics
- Code coverage reports
- Merge plans and instructions

## 📄 Root-Level Documentation

### `README.md`
Main project README with setup and usage instructions.

### `START_HERE.md`
Quick start guide for new developers.

### Configuration Documentation
- `COPILOT_INSTRUCTIONS.md` - GitHub Copilot integration guide
- `CI_LOCAL_STANDARDS_COMPARISON.md` - CI/CD and local testing standards
- `MYPY_CI_CONFIGURATION.md` - mypy type checking setup
- `MYPY_QUICK_REFERENCE.md` - Quick reference for mypy usage

## 🔍 Finding Documentation

### By Topic

**Deployment & Infrastructure:**
```bash
ls docs/deployment/
```

**Features & Implementation:**
```bash
ls docs/features/
```

**Troubleshooting & Fixes:**
```bash
ls docs/troubleshooting/
```

**Status & Progress:**
```bash
ls docs/status/
```

### Search All Documentation
```bash
# Search for a specific topic
grep -r "RSS metadata" docs/

# Find files by name pattern
find docs/ -name "*TELEMETRY*"
```

## 📊 Documentation Statistics

Total documentation files: ~150+
- Deployment: ~30 files
- Features: ~40 files
- Troubleshooting: ~35 files
- Status: ~25 files
- Archive: ~20 files

## 🔄 Recent Updates

**2025-10-20:**
- Reorganized all documentation into categorized folders
- Created this index file for easy navigation
- Moved 150+ markdown files from root to organized structure
- Kept only essential files in root (README, START_HERE)

## 💡 Documentation Best Practices

1. **New deployment docs** → Add to `/deployment/`
2. **New feature docs** → Add to `/features/`
3. **Bug fixes** → Add to `/troubleshooting/`
4. **Status updates** → Add to `/status/`
5. **Completed work** → Move to `/archive/` after some time

## 🔗 Related Resources

- [GitHub Repository](https://github.com/LocalNewsImpact/MizzouNewsCrawler)
- [Cloud Console](https://console.cloud.google.com/home/dashboard?project=mizzou-news-crawler)
- [CI/CD Pipeline](https://github.com/LocalNewsImpact/MizzouNewsCrawler/actions)

---

**Last Updated:** October 20, 2025
**Maintained By:** Development Team
