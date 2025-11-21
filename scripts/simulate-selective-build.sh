#!/bin/bash
# Simulate file changes and test service detection
# Useful for testing different commit scenarios without making actual changes

set -e

BLUE='\033[0;34m'
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Selective Service Build - Scenario Simulator${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo ""

# Scenarios
scenarios=(
  "crawler_only:src/crawler/link_extractor.py"
  "ml_feature:src/ml/classifier.py|src/cli/commands/analysis.py"
  "pytorch_upgrade:requirements-ml.txt"
  "db_migration:alembic/versions/001_initial.py"
  "api_endpoint:backend/app/routes.py|src/cli/commands/reports.py"
  "docs_only:README.md|docs/API.md"
  "base_upgrade:requirements-base.txt|pyproject.toml"
  "full_rebuild:Dockerfile.api|Dockerfile.processor|Dockerfile.crawler"
)

echo -e "${YELLOW}Available Scenarios:${NC}"
echo ""
for i in "${!scenarios[@]}"; do
  IFS=':' read -r name files <<< "${scenarios[$i]}"
  echo "  $((i+1)). $name"
  echo "     Files: $files" | tr '|' '\n' | sed 's/^/        /'
done
echo ""

read -p "Enter scenario number (1-${#scenarios[@]}) or 'custom': " choice

if [ "$choice" = "custom" ]; then
  read -p "Enter files separated by pipes (|): " custom_files
  scenario_files="$custom_files"
  scenario_name="custom"
else
  if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt "${#scenarios[@]}" ]; then
    echo -e "${RED}Invalid choice${NC}"
    exit 1
  fi
  
  IFS=':' read -r scenario_name scenario_files <<< "${scenarios[$((choice-1))]}"
fi

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Testing Scenario: ${YELLOW}$scenario_name${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo ""

# Create a temporary file with the scenario
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

# Create file list
echo "$scenario_files" | tr '|' '\n' > "$TEMP_DIR/files.txt"

echo -e "${YELLOW}Files in this scenario:${NC}"
cat "$TEMP_DIR/files.txt" | sed 's/^/  /'
echo ""

# Simulate git diff output
echo -e "${YELLOW}Simulating git diff output:${NC}"
cat "$TEMP_DIR/files.txt"
echo ""

# Initialize service flags
rebuild_base="false"
rebuild_ml_base="false"
rebuild_migrator="false"
rebuild_processor="false"
rebuild_api="false"
rebuild_crawler="false"

# Detection patterns (from the workflow)
base_patterns="(Dockerfile\.base|requirements-base\.txt|src/config\.py|pyproject\.toml|setup\.py)"
ml_base_patterns="(Dockerfile\.ml-base|requirements-ml\.txt)"
migrator_patterns="(Dockerfile\.migrator|requirements-migrator\.txt|alembic/versions/)"
processor_patterns="(Dockerfile\.processor|requirements-processor\.txt|src/pipeline/|src/ml/|src/services/classification_service\.py|src/cli/commands/analysis\.py|src/cli/commands/entity_extraction\.py|alembic/versions/)"
api_patterns="(Dockerfile\.api|requirements-api\.txt|backend/|src/models/api_backend\.py|src/cli/commands/cleaning\.py|src/cli/commands/reports\.py)"
crawler_patterns="(Dockerfile\.crawler|requirements-crawler\.txt|src/crawler/|src/services/|src/utils/|src/cli/commands/(discovery|verification|extraction|content_cleaning)\.py)"

# Check patterns
if cat "$TEMP_DIR/files.txt" | grep -qE "$base_patterns"; then
  rebuild_base="true"
fi

if cat "$TEMP_DIR/files.txt" | grep -qE "$ml_base_patterns"; then
  rebuild_ml_base="true"
fi

if cat "$TEMP_DIR/files.txt" | grep -qE "$migrator_patterns"; then
  rebuild_migrator="true"
fi

if cat "$TEMP_DIR/files.txt" | grep -qE "$processor_patterns"; then
  rebuild_processor="true"
fi

if cat "$TEMP_DIR/files.txt" | grep -qE "$api_patterns"; then
  rebuild_api="true"
fi

if cat "$TEMP_DIR/files.txt" | grep -qE "$crawler_patterns"; then
  rebuild_crawler="true"
fi

# Apply dependencies
if [ "$rebuild_base" = "true" ]; then
  rebuild_migrator="true"
  rebuild_processor="true"
  rebuild_api="true"
  rebuild_crawler="true"
fi

if [ "$rebuild_ml_base" = "true" ]; then
  rebuild_processor="true"
fi

echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}🚀 SERVICE BUILD PLAN${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"

count=0
if [ "$rebuild_base" = "true" ]; then
  echo -e "  ${GREEN}✅${NC} base"; ((count++))
else
  echo -e "  ${RED}⏭️ ${NC} base (skipped)"
fi

if [ "$rebuild_ml_base" = "true" ]; then
  echo -e "  ${GREEN}✅${NC} ml-base"; ((count++))
else
  echo -e "  ${RED}⏭️ ${NC} ml-base (skipped)"
fi

if [ "$rebuild_migrator" = "true" ]; then
  echo -e "  ${GREEN}✅${NC} migrator"; ((count++))
else
  echo -e "  ${RED}⏭️ ${NC} migrator (skipped)"
fi

if [ "$rebuild_processor" = "true" ]; then
  echo -e "  ${GREEN}✅${NC} processor"; ((count++))
else
  echo -e "  ${RED}⏭️ ${NC} processor (skipped)"
fi

if [ "$rebuild_api" = "true" ]; then
  echo -e "  ${GREEN}✅${NC} api"; ((count++))
else
  echo -e "  ${RED}⏭️ ${NC} api (skipped)"
fi

if [ "$rebuild_crawler" = "true" ]; then
  echo -e "  ${GREEN}✅${NC} crawler"; ((count++))
else
  echo -e "  ${RED}⏭️ ${NC} crawler (skipped)"
fi

echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${GREEN}📦 Result: $count service(s) will be rebuilt${NC}"
echo ""

# Show actual regex matches (for debugging)
if [ "${DEBUG:-false}" = "true" ]; then
  echo -e "${YELLOW}🔍 Debug Info:${NC}"
  echo ""
  echo "BASE matches:"
  cat "$TEMP_DIR/files.txt" | grep -E "$base_patterns" || echo "  (none)"
  echo ""
  echo "ML-BASE matches:"
  cat "$TEMP_DIR/files.txt" | grep -E "$ml_base_patterns" || echo "  (none)"
  echo ""
  echo "PROCESSOR matches:"
  cat "$TEMP_DIR/files.txt" | grep -E "$processor_patterns" || echo "  (none)"
  echo ""
  echo "API matches:"
  cat "$TEMP_DIR/files.txt" | grep -E "$api_patterns" || echo "  (none)"
  echo ""
  echo "CRAWLER matches:"
  cat "$TEMP_DIR/files.txt" | grep -E "$crawler_patterns" || echo "  (none)"
  echo ""
fi
