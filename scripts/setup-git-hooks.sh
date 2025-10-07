#!/bin/bash
set -euo pipefail

#######################################################################
# Setup Git Hooks for Pre-Deployment Validation
#
# This script installs a pre-push hook that runs validation tests
# before allowing git push to succeed.
#
# Usage:
#   ./scripts/setup-git-hooks.sh
#######################################################################

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
HOOKS_DIR="${PROJECT_ROOT}/.git/hooks"

echo "=========================================="
echo "Setting up Git hooks for pre-deployment validation"
echo "=========================================="
echo ""

# Ensure hooks directory exists
mkdir -p "$HOOKS_DIR"

# Create pre-push hook
cat > "${HOOKS_DIR}/pre-push" << 'EOF'
#!/bin/bash
set -euo pipefail

echo ""
echo "=========================================="
echo "Running pre-push validation..."
echo "=========================================="
echo ""

# Get the project root
HOOK_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$HOOK_DIR")"

cd "$PROJECT_ROOT"

# Run the validation script
if [ -x "scripts/pre-deploy-validation.sh" ]; then
    ./scripts/pre-deploy-validation.sh all || {
        echo ""
        echo "=========================================="
        echo "❌ PRE-PUSH VALIDATION FAILED"
        echo "=========================================="
        echo ""
        echo "Your changes did not pass validation."
        echo "Fix the issues above before pushing."
        echo ""
        echo "To skip this hook (NOT RECOMMENDED):"
        echo "  git push --no-verify"
        echo ""
        exit 1
    }
else
    echo "⚠️  Pre-deployment validation script not found"
    echo "   This is unusual - proceeding anyway"
fi

echo ""
echo "=========================================="
echo "✅ Pre-push validation passed!"
echo "=========================================="
echo ""
exit 0
EOF

# Make the hook executable
chmod +x "${HOOKS_DIR}/pre-push"

echo "✅ Pre-push hook installed at: ${HOOKS_DIR}/pre-push"
echo ""
echo "This hook will run validation before every git push."
echo "If validation fails, the push will be blocked."
echo ""
echo "To test the hook, run:"
echo "  git push --dry-run"
echo ""
echo "To bypass the hook (NOT RECOMMENDED):"
echo "  git push --no-verify"
echo ""
