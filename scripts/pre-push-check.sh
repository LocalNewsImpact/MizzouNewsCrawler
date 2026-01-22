#!/bin/bash
# Pre-push check script
# Run this before pushing to catch CI failures locally

set -e

echo "🔍 Running pre-push checks..."
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Activate venv
source venv/bin/activate

# Set PostgreSQL URL (adjust to match your local setup)
export DATABASE_URL="${DATABASE_URL:-postgresql://$(whoami)@localhost:5432/mizzou_news_crawler}"
export TEST_DATABASE_URL="$DATABASE_URL"
export TELEMETRY_DATABASE_URL="$DATABASE_URL"

echo -e "${YELLOW}Using DATABASE_URL: $DATABASE_URL${NC}"
echo ""

# 1. Run mypy
echo "📝 Running mypy..."
if python -m mypy --config-file=pyproject.toml src/; then
    echo -e "${GREEN}✓ mypy passed${NC}"
else
    echo -e "${RED}✗ mypy failed${NC}"
    exit 1
fi
echo ""

# 2. Run ruff
echo "📝 Running ruff..."
if python -m ruff check src/; then
    echo -e "${GREEN}✓ ruff passed${NC}"
else
    echo -e "${RED}✗ ruff failed - run 'ruff check --fix src/' to auto-fix${NC}"
    exit 1
fi
echo ""

# 3. Validate YAML syntax (MATCHES CI)
echo "📝 Validating YAML syntax..."
pip install -q PyYAML >/dev/null 2>&1 || true
find . -name "*.yaml" -o -name "*.yml" | while read -r file; do
  echo "  Checking $file..."
  python -c "import yaml; list(yaml.safe_load_all(open('$file')))" || exit 1
done
echo -e "${GREEN}✓ YAML validation passed${NC}"
echo ""

# 4. Run the quick argo tests (same as CI argo-quick job)
echo "🧪 Running argo-quick tests..."
if pytest -q --override-ini='addopts=' -p no:pytest-cov \
    tests/unit/test_argo_workflow_template.py \
    tests/unit/test_verification_no_head.py; then
    echo -e "${GREEN}✓ argo-quick tests passed${NC}"
else
    echo -e "${RED}✗ argo-quick tests failed${NC}"
    exit 1
fi
echo ""

# 5. Run unit tests (fast subset)
echo "🧪 Running unit tests..."
if pytest -q --override-ini='addopts=' -p no:pytest-cov tests/unit/ -k "not slow"; then
    echo -e "${GREEN}✓ unit tests passed${NC}"
else
    echo -e "${RED}✗ unit tests failed${NC}"
    exit 1
fi
echo ""

echo -e "${GREEN}✅ All pre-push checks passed!${NC}"
echo ""
echo "Safe to push to CI 🚀"
