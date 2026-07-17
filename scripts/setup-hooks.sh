#!/bin/bash

# Setup git hooks for local development
# This ensures local CI matches remote CI

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

echo "🔧 Installing git hooks..."

# Create pre-push hook
cat > "$REPO_ROOT/.git/hooks/pre-push" << 'EOF'
#!/bin/bash

# Git pre-push hook to run tests before pushing
# Prevents pushing code that will fail in CI
#
# Static-analysis steps (lint, type-check) run against a CLEAN CHECKOUT of the
# commit being pushed (via a temporary git worktree), so untracked scratch files
# in the working tree never affect the result. This mirrors CI, which runs on a
# fresh checkout of committed code only — the hook must test what is in git for
# push to origin, not the developer's dirty working tree.

# Skip CI for workflow-only changes (can't be tested locally anyway)
CHANGED_FILES=$(git diff --name-only @{upstream}..HEAD 2>/dev/null || git diff --name-only HEAD~1..HEAD)
NON_WORKFLOW_FILES=$(echo "$CHANGED_FILES" | grep -v '^\.github/workflows/' || true)

if [ -z "$NON_WORKFLOW_FILES" ]; then
    echo "⏭️  Skipping pre-push CI: Only GitHub Actions workflow files changed"
    echo "   (Workflows can't be tested locally - will validate on GitHub)"
    exit 0
fi

# Ensure Docker is in PATH (for macOS Docker Desktop)
export PATH="/usr/local/bin:/opt/homebrew/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"

# Setup log rotation (keep last 3 logs)
LOG_DIR="logs/pre-push"
mkdir -p "$LOG_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOGFILE="$LOG_DIR/pre-push-${TIMESTAMP}.log"

# Rotate logs - keep only the 3 most recent
ls -t "$LOG_DIR"/pre-push-*.log 2>/dev/null | tail -n +4 | xargs rm -f 2>/dev/null

echo "🚀 Pre-push hook: Running checks..."
echo "📝 Logging to: $LOGFILE"
echo ""

# ----------------------------------------------------------------------------
# Clean checkout of the commit being pushed, used for static-analysis steps.
# Only committed, tracked files exist here — no untracked scratch files.
# ----------------------------------------------------------------------------
REPO_ROOT="$(git rev-parse --show-toplevel)"
WORKTREE_PARENT="$(mktemp -d)"
WORKTREE="$WORKTREE_PARENT/committed"
cleanup_worktree() {
    git worktree remove --force "$WORKTREE" 2>/dev/null
    rm -rf "$WORKTREE_PARENT" 2>/dev/null
}
if ! git worktree add --detach --quiet "$WORKTREE" HEAD 2>>"$LOGFILE"; then
    echo "⚠️  Could not create clean worktree; falling back to working tree for lint/type checks" | tee -a "$LOGFILE"
    WORKTREE="$REPO_ROOT"
    cleanup_worktree() { :; }
fi

# Step 1: Run fast linting/formatting checks first (fail fast on simple errors)
# Runs against the committed checkout so untracked files are never linted.
echo "🔍 Step 1/4: Running linting checks (ruff, black, isort)..."
(
    cd "$WORKTREE" || exit 1
    source "$REPO_ROOT/venv/bin/activate" 2>/dev/null || true
    echo "  → Running ruff..." &&
    python -m ruff check . &&
    echo "  → Running black..." &&
    python -m black --check src/ tests/ web/ &&
    echo "  → Running isort..." &&
    python -m isort --check-only --profile black src/ tests/ web/
) 2>&1 | tee -a "$LOGFILE"
LINT_EXIT_CODE=${PIPESTATUS[0]}

if [ $LINT_EXIT_CODE -ne 0 ]; then
    cleanup_worktree
    echo ""
    echo "❌ Linting/formatting checks failed! Push aborted."
    echo "💡 Tip: Run 'make format' to auto-fix formatting issues"
    echo "📝 Full log saved to: $LOGFILE"
    exit 1
fi

echo "✅ Step 1/4: Linting checks passed"
echo ""

# Step 2: Run mypy type checking (matches CI mypy-strict job)
# Runs against the committed checkout so untracked files are never type-checked.
echo "🔍 Step 2/4: Running mypy type checking..."
(
    cd "$WORKTREE" || exit 1
    source "$REPO_ROOT/venv/bin/activate" 2>/dev/null || true
    python -m mypy src/ --ignore-missing-imports
) 2>&1 | tee -a "$LOGFILE"
MYPY_EXIT_CODE=${PIPESTATUS[0]}

if [ $MYPY_EXIT_CODE -ne 0 ]; then
    cleanup_worktree
    echo ""
    echo "❌ Type checking failed! Push aborted."
    echo "💡 Tip: Run 'make type-check' to see all type errors"
    echo "📝 Full log saved to: $LOGFILE"
    exit 1
fi

echo "✅ Step 2/4: Type checking passed"
echo ""

# Done with static analysis on the clean checkout.
cleanup_worktree

# Step 3: Validate Dockerfile dependencies (lightweight, no Docker build needed)
# Runs in the working tree: it intentionally verifies that build inputs exist
# on disk, including untracked artifacts such as models/productionmodel.pt.
echo "🚀 Step 3/4: Validating Dockerfile dependencies..."
if [ -f "./scripts/validate-dockerfile-deps.sh" ]; then
    ./scripts/validate-dockerfile-deps.sh 2>&1 | tee -a "$LOGFILE"
    DOCKER_VALIDATE_EXIT_CODE=${PIPESTATUS[0]}

    if [ $DOCKER_VALIDATE_EXIT_CODE -ne 0 ]; then
        echo ""
        echo "❌ Dockerfile validation failed! Push aborted."
        echo "📝 Full log saved to: $LOGFILE"
        exit 1
    fi
else
    echo "⚠️  scripts/validate-dockerfile-deps.sh not found, skipping"
fi

echo "✅ Step 3/4: Dockerfile validation passed"
echo ""

# Step 4: Run all tests including integration tests
# Runs in the working tree because some tests need untracked runtime artifacts
# (e.g. models/productionmodel.pt). Gate tests that scan the source tree
# enumerate git-tracked files (git ls-files), so untracked scratch files in the
# working tree are never tested.
echo "🚀 Step 4/4: Running all tests (unit + integration)..."
(
    source venv/bin/activate 2>/dev/null || true &&
    python -m pytest tests/ -q --tb=short
) 2>&1 | tee -a "$LOGFILE"
TEST_EXIT_CODE=${PIPESTATUS[0]}

if [ $TEST_EXIT_CODE -ne 0 ]; then
    echo ""
    echo "❌ Unit tests failed! Push aborted."
    echo "📝 Full log saved to: $LOGFILE"
    exit 1
fi

echo ""
echo "✅ All pre-push checks passed! Proceeding with push..."
echo "📝 Full log saved to: $LOGFILE"
exit 0
EOF

chmod +x "$REPO_ROOT/.git/hooks/pre-push"

echo "✅ Git hooks installed successfully!"
echo ""
echo "The pre-push hook will now run:"
echo "  1. Linting checks (ruff, black, isort) — clean checkout of committed code"
echo "  2. Type checking (mypy) - matches CI mypy-strict job — clean checkout"
echo "  3. Dockerfile dependency validation"
echo "  4. All tests (unit + integration)"
echo ""
echo "Static-analysis steps run against a temporary git worktree of HEAD, so"
echo "untracked scratch files in your working tree never affect the result."
echo ""
echo "To reinstall hooks later: ./scripts/setup-hooks.sh"
