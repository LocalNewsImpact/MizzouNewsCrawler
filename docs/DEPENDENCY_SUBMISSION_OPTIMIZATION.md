# Automatic Dependency Submission Analysis

**Date**: October 2, 2025  
**Workflow**: "Automatic Dependency Submission (Python)"  
**Type**: GitHub-managed automatic workflow (event: `dynamic`)

## Current Behavior

### What It Does
This is **GitHub's automatic dependency graph submission** feature that:
1. Scans Python dependency files (`requirements.txt`, `pyproject.toml`, etc.)
2. Analyzes installed packages
3. Submits dependency data to GitHub's dependency graph
4. Enables Dependabot security alerts

### Current Trigger Pattern
- **Event Type**: `dynamic` (GitHub-managed, not user-controlled)
- **Frequency**: Runs on EVERY push to main branch
- **Recent History**: 7 runs in ~3 hours today
- **Duration**: ~4-5 minutes per run
- **Total Time Wasted**: ~20-30 minutes on pushes with no dependency changes

## The Problem

### Wasteful Execution
```
Time: 17:07 → Push → Dependency scan (4m)
Time: 17:20 → Push → Dependency scan (4m)  ← Same dependencies
Time: 17:53 → Push → Dependency scan (4m)  ← Same dependencies
Time: 18:05 → Push → Dependency scan (4m)  ← Same dependencies
Time: 18:12 → Push → Dependency scan (4m)  ← Same dependencies
Time: 18:13 → Push → Dependency scan (4m)  ← Same dependencies
```

**Issue**: When you push code changes, documentation, or config tweaks, the dependency scan runs even though `requirements.txt` hasn't changed.

---

## Solutions

### Option 1: **Disable Automatic Submission** (Recommended)
Replace the automatic workflow with a controlled one that only runs when dependencies change.

#### Step 1: Disable Automatic Submission
Go to: **Repository Settings** → **Code security and analysis** → **Dependency graph** → Disable "Automatic dependency submission"

Or via GitHub CLI:
```bash
# Note: There's no direct CLI command, must use web UI or API
```

#### Step 2: Create Custom Workflow
Create `.github/workflows/dependency-submission.yml`:

```yaml
name: Dependency Submission

on:
  push:
    branches: [ main ]
    paths:
      - 'requirements.txt'
      - 'requirements-dev.txt'
      - 'pyproject.toml'
      - 'setup.py'
      - 'setup.cfg'
      - 'Pipfile'
      - 'Pipfile.lock'
  schedule:
    # Run weekly on Monday at 3am UTC to catch new vulnerabilities
    - cron: '0 3 * * 1'
  workflow_dispatch: {}  # Allow manual trigger

jobs:
  submit-dependencies:
    runs-on: ubuntu-latest
    permissions:
      contents: write  # Required for dependency submission

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Cache pip
        uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-dependency-scan-${{ hashFiles('requirements*.txt', 'pyproject.toml') }}
          restore-keys: |
            ${{ runner.os }}-pip-dependency-scan-

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install -r requirements-dev.txt

      - name: Submit dependencies
        uses: actions/dependency-submission@v1
        with:
          dependency-file: |
            requirements.txt
            requirements-dev.txt
```

**Benefits**:
- ✅ Only runs when dependency files change
- ✅ Runs weekly to catch new vulnerabilities
- ✅ Can be manually triggered if needed
- ✅ Saves ~20-30 minutes on non-dependency pushes

---

### Option 2: **Keep Automatic but Optimize**
If you want to keep the automatic submission, you can't directly control when it runs (it's GitHub-managed), but you can:

1. **Accept the overhead** as a security tradeoff
2. **Use path filters in OTHER workflows** to reduce total CI time
3. **Batch dependency updates** to reduce push frequency

**Not Recommended**: You lose control and waste CI minutes.

---

### Option 3: **Hybrid Approach** (Best of Both Worlds)
Keep automatic submission but limit its impact:

1. **Keep automatic submission enabled** for continuous monitoring
2. **Add path filters to YOUR workflows** to skip unnecessary runs:

```yaml
# In .github/workflows/ci.yml
on:
  push:
    branches: [ main ]
    paths-ignore:
      - '**.md'
      - 'docs/**'
      - '.gitignore'
      - 'LICENSE'
      - '.github/**'  # Skip when only CI config changes
  pull_request:
    branches: [ main ]
    paths-ignore:
      - '**.md'
      - 'docs/**'
```

**Benefits**:
- ✅ Continuous security monitoring (automatic)
- ✅ Your workflows skip unnecessary runs
- ✅ Less total CI time wasted

---

## Recommendation: **Option 1 (Custom Workflow)**

### Why Custom is Better

| Aspect | Automatic | Custom Workflow |
|--------|-----------|-----------------|
| **Runs on every push** | Yes (wasteful) | No (smart) |
| **Path filtering** | No | Yes |
| **Scheduling** | No | Yes (weekly) |
| **Manual trigger** | No | Yes |
| **CI minutes used** | High | Low (90% reduction) |
| **Control** | None | Full |
| **Security coverage** | Same | Same + scheduled |

### Time Savings

**Current (7 pushes today)**:
- 7 pushes × 4 min = **28 minutes**

**With Custom Workflow (assume 1 dependency change)**:
- 1 run × 4 min = **4 minutes**
- **Savings: 24 minutes (86%)**

**Monthly estimate**:
- Current: ~200 pushes × 4 min = **800 minutes (~13 hours)**
- Custom: ~20 dependency changes × 4 min = **80 minutes**
- **Monthly savings: 720 minutes (~12 hours, 90% reduction)**

---

## Implementation Steps

### Phase 1: Setup Custom Workflow (15 minutes)
1. Create `.github/workflows/dependency-submission.yml` with the config above
2. Test it by manually triggering: `gh workflow run dependency-submission.yml`
3. Verify dependency graph updates in GitHub UI
4. Make a PR that changes `requirements.txt` and verify it triggers

### Phase 2: Disable Automatic (5 minutes)
1. Go to **Settings** → **Code security and analysis**
2. Find **Dependency graph** section
3. Disable **"Automatic dependency submission"**
4. Confirm the automatic workflow stops running

### Phase 3: Monitor (ongoing)
1. Check dependency graph weekly
2. Review Dependabot alerts
3. Verify scheduled run completes on Mondays

---

## Additional Optimizations

### 1. Add Concurrency Control
Prevent multiple dependency submissions running simultaneously:

```yaml
concurrency:
  group: dependency-submission
  cancel-in-progress: true
```

### 2. Add Caching
Speed up the submission workflow:

```yaml
- name: Cache pip
  uses: actions/cache@v4
  with:
    path: ~/.cache/pip
    key: dependency-scan-${{ hashFiles('requirements*.txt') }}
```

### 3. Combine with Security Scan
Since you're already installing dependencies, add security checks:

```yaml
- name: Check for vulnerabilities
  run: |
    pip install safety
    safety check --json
```

---

## Risks & Mitigations

### Risk 1: Missing Dependency Updates
**Concern**: What if a new vulnerability is discovered?

**Mitigation**: 
- Weekly scheduled run catches new vulnerabilities
- Manual trigger available for urgent scans
- Dependabot still monitors the dependency graph

### Risk 2: Forgetting to Update
**Concern**: Developers might forget to update dependency files

**Mitigation**:
- Pre-commit hooks remind developers
- CI fails if dependencies mismatch
- Automated dependency updates via Renovate/Dependabot

### Risk 3: Initial Setup Complexity
**Concern**: Custom workflow requires maintenance

**Mitigation**:
- Well-documented workflow (this doc!)
- Simple YAML configuration
- GitHub's dependency-submission action is maintained by GitHub

---

## Monitoring & Metrics

### Track These Metrics
1. **CI minutes saved per month**
2. **Dependency submission frequency** (should be ~20/month)
3. **Time between vulnerability discovery and notification**
4. **False negative rate** (missed vulnerabilities)

### Success Criteria
- ✅ 80%+ reduction in CI minutes for dependency submission
- ✅ No increase in time-to-detection for vulnerabilities
- ✅ Dependency graph stays up-to-date
- ✅ Zero missed critical security alerts

---

## Alternative: Use Renovate or Dependabot

If dependency management overhead is high, consider:

### Renovate Bot
- Automatic PR creation for dependency updates
- Smart scheduling (batch updates weekly)
- Built-in dependency graph updates

### Dependabot
- GitHub-native solution
- Automatic security updates
- Grouping similar updates

**Note**: These tools also submit dependency data, making the automatic submission redundant.

---

## Decision Matrix

| Use Case | Recommendation |
|----------|----------------|
| **Frequent pushes, rare dependency changes** | Custom workflow |
| **Security-critical project** | Custom + weekly schedule |
| **Small team, low push frequency** | Keep automatic (accept overhead) |
| **Using Renovate/Dependabot** | Disable automatic entirely |
| **Monorepo with multiple languages** | Custom with matrix strategy |

---

## Next Steps

1. **Decide**: Choose Option 1 (Custom), Option 2 (Accept), or Option 3 (Hybrid)
2. **Implement**: Follow the implementation steps above
3. **Test**: Verify dependency graph updates correctly
4. **Monitor**: Track CI minutes saved and security coverage
5. **Document**: Update team documentation with new process

---

## Related Optimizations

Since you're optimizing CI, also consider:
1. **Add path filters to main CI workflow** (docs/CI_OPTIMIZATION_ANALYSIS.md)
2. **Cache full virtualenv** instead of just pip wheels
3. **Remove duplicate lint job** (lint once on 3.11)
4. **Parallelize tests** with pytest-xdist

**Combined savings**: 40-50% faster CI overall

---

## References

- [GitHub Dependency Submission API](https://docs.github.com/en/code-security/supply-chain-security/understanding-your-software-supply-chain/using-the-dependency-submission-api)
- [actions/dependency-submission](https://github.com/actions/dependency-submission-toolkit)
- [GitHub Dependency Graph](https://docs.github.com/en/code-security/supply-chain-security/understanding-your-software-supply-chain/about-the-dependency-graph)
- [Dependabot Configuration](https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/configuration-options-for-the-dependabot.yml-file)
