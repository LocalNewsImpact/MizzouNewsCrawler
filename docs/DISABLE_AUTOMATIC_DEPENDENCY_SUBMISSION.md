# Disabling Automatic Dependency Submission

## Current Status
✅ **Custom workflow created**: `.github/workflows/dependency-submission.yml`
✅ **Workflow pushed to GitHub**: Commit 80bbc26
✅ **Workflow registered**: Active and ready to use

⚠️ **Automatic submission still running**: Need to disable via GitHub UI

---

## Steps to Complete Setup

### Step 1: Disable Automatic Dependency Submission

**You must do this through the GitHub web UI:**

1. Go to: https://github.com/LocalNewsImpact/MizzouNewsCrawler/settings/security_analysis

2. Scroll to the **"Dependency graph"** section

3. Look for **"Automatic dependency submission"** or similar setting

4. **Uncheck/Disable** the automatic submission feature

**Alternative locations to check:**
- Settings → Code security and analysis → Dependency graph
- Settings → Security → Dependency graph
- Settings → Actions → General → Allow actions (check permissions)

### Step 2: Verify Automatic Workflow Stops

After disabling, wait 5 minutes and check:

```bash
gh run list --limit 10 --json workflowName,event | jq '.[] | select(.workflowName == "Automatic Dependency Submission")'
```

You should see no new runs with `event: "dynamic"` after disabling.

### Step 3: Test Custom Workflow (Optional)

Once automatic submission is disabled, test the custom workflow:

```bash
# Manual trigger
gh workflow run "Dependency Submission"

# Check it runs
gh run watch
```

### Step 4: Test Path-Based Triggering

Make a non-dependency change to verify the workflow DOESN'T run:

```bash
# Change a markdown file
echo "Test" >> README.md
git add README.md
git commit -m "test: Verify dependency workflow doesn't trigger"
git push

# Check workflows - should NOT see "Dependency Submission"
gh run list --limit 5
```

Then test that it DOES run when dependencies change:

```bash
# Touch a dependency file
touch requirements.txt
git add requirements.txt
git commit -m "test: Verify dependency workflow triggers"
git push

# Check workflows - SHOULD see "Dependency Submission"
gh run list --limit 5
```

---

## Expected Behavior After Setup

### ✅ Custom Workflow Will Run When:
- **Dependency files change**: `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`
- **Weekly schedule**: Monday at 3am UTC (catches new vulnerabilities)
- **Manual trigger**: `gh workflow run "Dependency Submission"`

### ❌ Custom Workflow Will NOT Run When:
- Code changes (`.py` files)
- Documentation changes (`.md` files)
- Configuration changes (non-dependency)
- Test changes

### ⏱️ Time Savings

**Before (Automatic on every push)**:
- 7 pushes today = 7 runs × 4 min = **28 minutes**
- Estimated monthly: 200 pushes × 4 min = **13 hours**

**After (Custom conditional)**:
- Only runs when dependencies change (~20 times/month)
- 20 runs × 4 min = **80 minutes/month**
- **Savings: ~12 hours/month (90% reduction)**

---

## Troubleshooting

### Problem: Can't find "Automatic dependency submission" setting

**Solution**: GitHub may have changed the UI. Try:
1. Search settings page for "dependency" or "submission"
2. Check under Actions → General → Workflow permissions
3. Contact GitHub support to disable the feature

### Problem: Automatic workflow still runs after disabling

**Possible causes**:
- Setting takes time to propagate (wait 15 minutes)
- Feature is org-level (check organization settings)
- Workflow is triggered by a different mechanism

**Solution**: Check workflow permissions:
```bash
gh api repos/LocalNewsImpact/MizzouNewsCrawler/actions/permissions
```

### Problem: Custom workflow doesn't trigger on dependency changes

**Debug**:
1. Check workflow syntax: `gh workflow view "Dependency Submission"`
2. Check path filters match your files
3. Check Actions permissions: Settings → Actions → General
4. View workflow logs: `gh run view <run-id> --log`

### Problem: "Advanced-security/component-detection" action fails

**Solution**: This is the same action GitHub uses. If it fails:
1. Check Python setup step succeeded
2. Verify dependencies install correctly
3. Check action permissions (needs `contents: write`)

---

## Monitoring

### Weekly Check (Mondays after 3am UTC)

Verify the scheduled run completes:

```bash
# Check for Monday runs
gh run list --workflow "Dependency Submission" --limit 5

# View logs
gh run view <run-id> --log
```

### Monthly Review

Check CI time savings:

```bash
# Count dependency submission runs this month
gh run list --workflow "Dependency Submission" --limit 100 --json createdAt | \
  jq '[.[] | select(.createdAt | startswith("2025-10"))] | length'

# Should be ~20-25 runs/month vs ~200 with automatic
```

---

## Next Steps

1. ✅ **Disable automatic submission** (GitHub UI - **DO THIS NOW**)
2. ⏳ Wait for current automatic run to complete
3. ⏳ Verify no new automatic runs appear
4. ⏳ Test custom workflow manually (optional)
5. ⏳ Test path-based triggering (optional)
6. ⏳ Monitor for one week to confirm behavior

---

## Related Documentation

- See `docs/DEPENDENCY_SUBMISSION_OPTIMIZATION.md` for full analysis
- See `docs/CI_OPTIMIZATION_ANALYSIS.md` for additional CI improvements
- See `.github/workflows/dependency-submission.yml` for workflow configuration

---

## Questions?

If you need help or the automatic submission won't disable, let me know and I can:
1. Research alternative approaches
2. Help contact GitHub support
3. Create a workaround solution

