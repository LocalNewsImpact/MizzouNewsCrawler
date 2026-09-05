#!/bin/bash

# Install the pre-push hook: what CI runs, before the push.
#
# The hook runs `make check` -- lint, typecheck, test, test-integration,
# the four stages lnic-contracts' python-checks.yml runs on GitHub -- on
# a clean worktree of the commit being pushed. Same targets, same
# scripts, same virtualenv; the one thing CI adds is the image the
# targets run in.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

echo "🔧 Installing git hooks..."

# Create pre-push hook
cat > "$REPO_ROOT/.git/hooks/pre-push" << 'EOF'
#!/bin/bash

# Git pre-push hook: `make check` on a clean worktree of the commit being
# pushed. Refuses the push if any stage fails.
#
# A CLEAN WORKTREE, not the working tree. CI checks out the commit and
# nothing else, so the hook does the same: untracked scratch files are
# not linted, a stray local module cannot make a test pass, and a file
# that was never `git add`ed fails here rather than on GitHub. The
# worktree has no virtualenv of its own, so this checkout's is passed
# in as VENV=.
#
# Branch DELETIONS have nothing to test — pre-push receives refspecs on
# stdin as "<local_ref> <local_sha> <remote_ref> <remote_sha>"; a deletion's
# local_sha is all zeros. Without this, deleting a remote branch ran the
# full CI suite (discovered 2026-07-19).
ZERO=0000000000000000000000000000000000000000
PUSH_SHA=""
BASE_SHA=""
while read -r local_ref local_sha remote_ref remote_sha; do
    [ "$local_sha" != "$ZERO" ] || continue
    PUSH_SHA="$local_sha"
    BASE_SHA="$remote_sha"
done
if [ -z "$PUSH_SHA" ]; then
    echo "⏭️  Skipping pre-push CI: branch deletion(s) only"
    exit 0
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"

# Skip the suite for a documentation-only push. The workflow's `changes`
# job asks scripts/ci/docs-only.sh the same question about the same
# range -- the commits the push adds -- so the two cannot disagree. The
# range is what the remote has to what it will have; for a new branch,
# where it has nothing yet, from the merge-base with main, which is the
# diff the pull request will show.
if [ "$BASE_SHA" = "$ZERO" ] || ! git cat-file -e "$BASE_SHA^{commit}" 2>/dev/null; then
    BASE_SHA="$(git merge-base origin/main "$PUSH_SHA" 2>/dev/null || true)"
fi
if [ -n "$BASE_SHA" ] && [ -x "$REPO_ROOT/scripts/ci/docs-only.sh" ] \
   && "$REPO_ROOT/scripts/ci/docs-only.sh" "$BASE_SHA" "$PUSH_SHA"; then
    echo "⏭️  Skipping pre-push CI: documentation only (nothing the suite covers)"
    exit 0
fi

# Ensure Docker is in PATH (for macOS Docker Desktop)
export PATH="/usr/local/bin:/opt/homebrew/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"

# Resolve the virtualenv. A linked worktree has no .venv of its own:
# `git rev-parse --show-toplevel` returns the worktree, and a hook that
# looked only there carried on under whatever python was on PATH --
# pyenv's, typically -- and failed with "No module named ruff" on a push
# that was fine. The venv lives in the primary checkout, which is the
# parent of the common git dir.
VENV_DIR="$REPO_ROOT/.venv"
if [ ! -x "$VENV_DIR/bin/python" ]; then
    COMMON_DIR="$(git rev-parse --git-common-dir)"
    case "$COMMON_DIR" in
        /*) ;;
        *) COMMON_DIR="$REPO_ROOT/$COMMON_DIR" ;;
    esac
    CANDIDATE="$(cd "$(dirname "$COMMON_DIR")" 2>/dev/null && pwd)/.venv"
    if [ -x "$CANDIDATE/bin/python" ]; then
        VENV_DIR="$CANDIDATE"
        echo "🔗 Worktree detected; using the primary checkout's virtualenv"
    fi
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "❌ No virtualenv found at $REPO_ROOT/.venv or in the primary checkout."
    echo "   The hook cannot mirror CI without it. Run: make setup"
    exit 1
fi

export VIRTUAL_ENV="$VENV_DIR"
export PATH="$VENV_DIR/bin:$PATH"

# Fail loudly rather than part-way through: a venv without the tooling
# produces "No module named ruff" one stage in, which reads as a code
# problem rather than an environment one.
if ! python -m ruff --version >/dev/null 2>&1; then
    echo "❌ ruff is not installed in the virtualenv."
    echo "   The hook cannot mirror CI without it. Run: make setup"
    exit 1
fi

# Setup log rotation (keep last 3 logs)
LOG_DIR="$REPO_ROOT/logs/pre-push"
mkdir -p "$LOG_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOGFILE="$LOG_DIR/pre-push-${TIMESTAMP}.log"
# Stable path for live tailing (VS Code task "Local CI: watch live")
ln -sf "pre-push-${TIMESTAMP}.log" "$LOG_DIR/latest.log"
# macOS notification helper — ambient progress visibility without a terminal
notify() {
    command -v osascript >/dev/null 2>&1 &&         osascript -e "display notification \"$2\" with title \"local CI: $1\"" 2>/dev/null || true
}
notify "started" "make check running — tail logs/pre-push/latest.log"

# Rotate logs - keep only the 3 most recent
ls -t "$LOG_DIR"/pre-push-*.log 2>/dev/null | tail -n +4 | xargs rm -f 2>/dev/null

echo "🚀 Pre-push hook: make check on $(git rev-parse --short "$PUSH_SHA")"
echo "📝 Logging to: $LOGFILE"
echo ""

# ----------------------------------------------------------------------------
# Clean checkout of the commit being pushed. Only committed, tracked files
# exist here — no untracked scratch files.
# ----------------------------------------------------------------------------
WORKTREE_PARENT="$(mktemp -d)"
WORKTREE="$WORKTREE_PARENT/committed"
cleanup_worktree() {
    git worktree remove --force "$WORKTREE" 2>/dev/null
    rm -rf "$WORKTREE_PARENT" 2>/dev/null
}
if ! git worktree add --detach --quiet "$WORKTREE" "$PUSH_SHA" 2>>"$LOGFILE"; then
    echo "⚠️  Could not create clean worktree; falling back to the working tree" | tee -a "$LOGFILE"
    WORKTREE="$REPO_ROOT"
    cleanup_worktree() { :; }
fi

(
    cd "$WORKTREE" || exit 1
    make VENV="$VENV_DIR" check
) 2>&1 | tee -a "$LOGFILE"
CHECK_EXIT_CODE=${PIPESTATUS[0]}
cleanup_worktree

if [ "$CHECK_EXIT_CODE" -ne 0 ]; then
    echo ""
    echo "❌ make check failed! Push aborted."
    notify "FAILED" "make check failed"
    if ! docker info >/dev/null 2>&1; then
        echo "   Docker is not running. make test-integration needs the compose Postgres,"
        echo "   and CI runs it, so the hook cannot mirror CI without it."
    fi
    echo "💡 Run the failed stage by name to iterate: make lint / typecheck / test / test-integration"
    echo "   Formatting: make format"
    echo "📝 Full log saved to: $LOGFILE"
    exit 1
fi

echo ""
notify "passed" "make check green — pushing"
echo "✅ make check passed! Proceeding with push..."
echo "📝 Full log saved to: $LOGFILE"
exit 0
EOF

chmod +x "$REPO_ROOT/.git/hooks/pre-push"

echo "✅ Git hooks installed successfully!"
echo ""
echo "The pre-push hook runs \`make check\` -- lint, typecheck, test,"
echo "test-integration -- on a clean worktree of the commit being pushed,"
echo "with this checkout's virtualenv. These are the stages CI runs, by the"
echo "same scripts; CI's one difference is that they run inside the CI image."
echo ""
echo "A documentation-only push (scripts/ci/docs-only.sh decides, for the"
echo "hook and for CI) skips the suite. Docker must be running: the"
echo "integration stage uses the compose Postgres."
echo ""
echo "To reinstall hooks later: ./scripts/setup-hooks.sh"
