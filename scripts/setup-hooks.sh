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

# Branch DELETIONS have nothing to test — pre-push receives refspecs on
# stdin as "<local_ref> <local_sha> <remote_ref> <remote_sha>"; a deletion's
# local_sha is all zeros. Without this, deleting a remote branch ran the
# full CI suite (discovered 2026-07-19).
ZERO=0000000000000000000000000000000000000000
ANY_NON_DELETE=false
while read -r local_ref local_sha remote_ref remote_sha; do
    [ "$local_sha" != "$ZERO" ] && ANY_NON_DELETE=true
done
if [ "$ANY_NON_DELETE" = "false" ]; then
    echo "⏭️  Skipping pre-push CI: branch deletion(s) only"
    exit 0
fi

# Skip CI for workflow-only / docs-only changes (nothing the test suite covers).
# Mirrors the `changes` gate in .github/workflows/ci.yml so local and remote
# agree on what counts as "code".
CHANGED_FILES=$(git diff --name-only @{upstream}..HEAD 2>/dev/null || git diff --name-only HEAD~1..HEAD)
CODE_FILES=$(echo "$CHANGED_FILES" | grep -vE '^(\.github/workflows/|docs/|scripts/setup-hooks\.sh$)' | grep -vE '\.md$' || true)

if [ -z "$CODE_FILES" ]; then
    echo "⏭️  Skipping pre-push CI: only workflow/docs changes (nothing the suite covers)"
    echo "   (These can't be tested locally - CI will validate on GitHub)"
    exit 0
fi

# Ensure Docker is in PATH (for macOS Docker Desktop)
export PATH="/usr/local/bin:/opt/homebrew/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"

# Setup log rotation (keep last 3 logs)
LOG_DIR="logs/pre-push"
mkdir -p "$LOG_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOGFILE="$LOG_DIR/pre-push-${TIMESTAMP}.log"
# Stable path for live tailing (VS Code task "Local CI: watch live")
ln -sf "pre-push-${TIMESTAMP}.log" "$LOG_DIR/latest.log"
# macOS notification helper — ambient progress visibility without a terminal
notify() {
    command -v osascript >/dev/null 2>&1 &&         osascript -e "display notification \"$2\" with title \"local CI: $1\"" 2>/dev/null || true
}
notify "started" "pre-push checks running — tail logs/pre-push/latest.log"

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
    source "$REPO_ROOT/.venv/bin/activate" 2>/dev/null || true
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
    notify "FAILED" "Linting/formatting checks failed"
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
    source "$REPO_ROOT/.venv/bin/activate" 2>/dev/null || true
    python -m mypy src/ --ignore-missing-imports
) 2>&1 | tee -a "$LOGFILE"
MYPY_EXIT_CODE=${PIPESTATUS[0]}

if [ $MYPY_EXIT_CODE -ne 0 ]; then
    cleanup_worktree
    echo ""
    echo "❌ Type checking failed! Push aborted."
    notify "FAILED" "Type checking failed"
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
    notify "FAILED" "Dockerfile validation failed"
        echo "📝 Full log saved to: $LOGFILE"
        exit 1
    fi
else
    echo "⚠️  scripts/validate-dockerfile-deps.sh not found, skipping"
fi

echo "✅ Step 3/4: Dockerfile validation passed"
echo ""

# Steps 4-6 run the two test suites in succession and ACCUMULATE coverage
# across both (via --cov-append), then gate on the COMBINED total in Step 6 —
# neither suite alone can reach the threshold. Erase stale data first so the
# run starts clean. addopts is overridden per phase so its single
# --cov-fail-under=78 doesn't fire mid-succession; the combined check is Step 6.
(source .venv/bin/activate 2>/dev/null || true; python -m coverage erase) >/dev/null 2>&1

# Step 4: Main test suite (unit + SQLite integration), excluding PostgreSQL.
# Runs in the working tree because some tests need untracked runtime artifacts
# (e.g. models/productionmodel.pt). Gate tests that scan the source tree
# enumerate git-tracked files (git ls-files), so untracked scratch files in the
# working tree are never tested. PostgreSQL-marked tests run separately in
# Step 5, so the two suites never contend for a single database.
echo "🚀 Step 4/6: Running main test suite (unit + integration, excluding PostgreSQL)..."
(
    source .venv/bin/activate 2>/dev/null || true &&
    python -m pytest tests/ -q --tb=short --override-ini="addopts=" \
        -p no:postgresql -m "not postgres and not docker and not local_scripts" \
        --cov=src --cov-append --cov-report=
) 2>&1 | tee -a "$LOGFILE"
TEST_EXIT_CODE=${PIPESTATUS[0]}

if [ $TEST_EXIT_CODE -ne 0 ]; then
    echo ""
    echo "❌ Main test suite failed! Push aborted."
    notify "FAILED" "Main test suite failed"
    echo "📝 Full log saved to: $LOGFILE"
    exit 1
fi

echo "✅ Step 4/6: Main test suite passed"
echo ""

# Step 5: PostgreSQL suite, run in succession against a docker PostgreSQL.
# Mirrors CI's dedicated PostgreSQL job. Uses the docker-compose 'postgres'
# service and a throwaway database, so it never touches a real dev database and
# never runs at the same time as the main suite. The local gate is meant to
# MIRROR remote CI, so Docker being unavailable is a HARD FAILURE (the push is
# blocked), not a silent skip — otherwise a Postgres-only regression sails past
# the local gate and only surfaces in remote CI. Set SKIP_PG=1 to deliberately
# opt out for the rare case where you knowingly want to defer to CI.
echo "🐘 Step 5/6: Running PostgreSQL suite (docker)..."

if [ "${SKIP_PG:-}" = "1" ]; then
    echo "⚠️  SKIP_PG=1 set; deliberately skipping PostgreSQL suite (CI will run it)." | tee -a "$LOGFILE"
    echo "✅ Step 5/6: PostgreSQL suite skipped (SKIP_PG=1)"
    echo ""
else
DOCKER_COMPOSE=""
if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    DOCKER_COMPOSE="docker-compose"
fi

if [ -z "$DOCKER_COMPOSE" ] || ! docker info >/dev/null 2>&1; then
    echo ""
    echo "❌ Docker is not available — the PostgreSQL suite cannot run, so this"
    echo "   push would NOT mirror remote CI. Push aborted."
    echo "   → Start Docker Desktop and re-push, or run with SKIP_PG=1 to"
    echo "     deliberately defer the Postgres suite to CI (not recommended)."
    echo "❌ Docker not available; PostgreSQL suite could not run. Push aborted." >> "$LOGFILE"
    notify "FAILED" "Docker unavailable; PostgreSQL suite could not run"
    echo "📝 Full log saved to: $LOGFILE"
    exit 1
else
    PG_TESTDB="mizzou_prepush"
    export TEST_DATABASE_URL="postgresql://mizzou_user:mizzou_pass@127.0.0.1:5432/${PG_TESTDB}"
    export DATABASE_URL="$TEST_DATABASE_URL"

    $DOCKER_COMPOSE up -d postgres >>"$LOGFILE" 2>&1

    PG_READY=""
    for _ in $(seq 1 30); do
        if $DOCKER_COMPOSE exec -T postgres pg_isready -U mizzou_user -d mizzou >/dev/null 2>&1; then
            PG_READY=1
            break
        fi
        sleep 1
    done

    if [ -z "$PG_READY" ]; then
        echo ""
        echo "❌ PostgreSQL container did not become ready in time; the suite could"
        echo "   not run, so this push would NOT mirror remote CI. Push aborted."
        echo "   → Check 'docker compose logs postgres', then re-push."
        echo "❌ PostgreSQL did not become ready; suite could not run. Push aborted." >> "$LOGFILE"
        notify "FAILED" "PostgreSQL did not become ready; suite could not run"
        echo "📝 Full log saved to: $LOGFILE"
        exit 1
    else
        # Fresh throwaway database, migrated to head, then run the suite.
        $DOCKER_COMPOSE exec -T postgres dropdb -U mizzou_user --if-exists "$PG_TESTDB" >>"$LOGFILE" 2>&1
        $DOCKER_COMPOSE exec -T postgres createdb -U mizzou_user "$PG_TESTDB" >>"$LOGFILE" 2>&1
        (
            source .venv/bin/activate 2>/dev/null || true &&
            alembic upgrade head &&
            python -m pytest tests/ -q --tb=short --override-ini="addopts=" \
                -p no:postgresql -m "postgres and not docker" \
                --cov=src --cov-append --cov-report=
        ) 2>&1 | tee -a "$LOGFILE"
        PG_EXIT_CODE=${PIPESTATUS[0]}
        $DOCKER_COMPOSE exec -T postgres dropdb -U mizzou_user --if-exists "$PG_TESTDB" >>"$LOGFILE" 2>&1

        if [ $PG_EXIT_CODE -ne 0 ]; then
            echo ""
            echo "❌ PostgreSQL suite failed! Push aborted."
    notify "FAILED" "PostgreSQL suite failed"
            echo "📝 Full log saved to: $LOGFILE"
            exit 1
        fi
    fi
fi

echo "✅ Step 5/6: PostgreSQL suite complete"
echo ""
fi  # end SKIP_PG guard

# Step 6: Combined coverage gate. Steps 4 and 5 accumulated coverage via
# --cov-append; enforce the 78% threshold on the COMBINED total here. If the
# PostgreSQL suite was skipped (no Docker), this checks the main suite alone,
# which matches CI's coverage job and still clears the threshold.
echo "📊 Step 6/6: Checking combined coverage (fail-under 78%)..."
(
    source .venv/bin/activate 2>/dev/null || true &&
    python -m coverage report --fail-under=78
) 2>&1 | tee -a "$LOGFILE"
COV_EXIT_CODE=${PIPESTATUS[0]}

if [ $COV_EXIT_CODE -ne 0 ]; then
    echo ""
    echo "❌ Combined coverage below 78%! Push aborted."
    notify "FAILED" "Combined coverage below 78%"
    echo "📝 Full log saved to: $LOGFILE"
    exit 1
fi

echo "✅ Step 6/6: Combined coverage gate passed"

echo ""
notify "passed" "all checks green — pushing"
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
echo "  4. Main test suite (unit + integration, excluding PostgreSQL)"
echo "  5. PostgreSQL suite against a docker PostgreSQL (skipped if Docker is down)"
echo "  6. Combined coverage gate (>=78% across steps 4-5)"
echo ""
echo "Static-analysis steps run against a temporary git worktree of HEAD, so"
echo "untracked scratch files in your working tree never affect the result."
echo "The main and PostgreSQL suites run in succession (not one shared DB) and"
echo "their coverage is accumulated, then gated on the combined total."
echo ""
echo "To reinstall hooks later: ./scripts/setup-hooks.sh"
