#!/bin/bash
# Selective service build - Local testing and dry-run script
# This allows you to test the service detection logic before pushing to main

set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default to comparing HEAD~1..HEAD unless otherwise specified
BASE_REF="${1:-HEAD~1}"
HEAD_REF="${2:-HEAD}"

echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Selective Service Build - Local Detection Test${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo ""
echo "📊 Comparing: $BASE_REF → $HEAD_REF"
echo ""

# Get changed files
CHANGED_FILES=$(git diff --name-only "$BASE_REF" "$HEAD_REF" 2>/dev/null || echo "")

if [ -z "$CHANGED_FILES" ]; then
  echo -e "${RED}❌ No changed files found. Are both refs valid?${NC}"
  echo "   Try: $0 origin/main HEAD"
  exit 1
fi

echo -e "${YELLOW}📝 Changed Files:${NC}"
echo "$CHANGED_FILES" | sed 's/^/   /'
echo ""

# Initialize service flags
REBUILD_BASE="false"
REBUILD_ML_BASE="false"
REBUILD_MIGRATOR="false"
REBUILD_PROCESSOR="false"
REBUILD_API="false"
REBUILD_CRAWLER="false"

# Function to check pattern and report
check_pattern() {
  local service_name=$1
  local patterns=$2
  
  if echo "$CHANGED_FILES" | grep -qE "$patterns"; then
    return 0  # Match found
  fi
  return 1  # No match
}

# Detection logic (mirrors the workflow)

echo -e "${BLUE}🔍 Analyzing changes...${NC}"
echo ""

# BASE IMAGE
if check_pattern "BASE" '(Dockerfile\.base|requirements-base\.txt|src/config\.py|pyproject\.toml|setup\.py)'; then
  echo -e "${GREEN}✅ BASE${NC} - Base image changes detected"
  REBUILD_BASE="true"
else
  echo -e "${RED}⏭️  BASE${NC} - No base image changes"
fi

# ML-BASE IMAGE
if check_pattern "ML-BASE" '(Dockerfile\.ml-base|requirements-ml\.txt)'; then
  echo -e "${GREEN}✅ ML-BASE${NC} - ML dependencies changes detected"
  REBUILD_ML_BASE="true"
else
  echo -e "${RED}⏭️  ML-BASE${NC} - No ML-base changes"
fi

# Dependency handling: BASE → all services
if [ "$REBUILD_BASE" = "true" ]; then
  echo -e "${YELLOW}🔗 BASE changed → rebuilding all dependent services${NC}"
  REBUILD_MIGRATOR="true"
  REBUILD_PROCESSOR="true"
  REBUILD_API="true"
  REBUILD_CRAWLER="true"
fi

# Dependency handling: ML-BASE → PROCESSOR
if [ "$REBUILD_ML_BASE" = "true" ]; then
  echo -e "${YELLOW}🔗 ML-BASE changed → rebuilding processor${NC}"
  REBUILD_PROCESSOR="true"
fi

# MIGRATOR
if check_pattern "MIGRATOR" '(Dockerfile\.migrator|requirements-migrator\.txt|alembic/versions/)'; then
  echo -e "${GREEN}✅ MIGRATOR${NC} - Migration changes detected"
  REBUILD_MIGRATOR="true"
else
  # Check if it's the first time through (not already set by BASE)
  if [ "$REBUILD_MIGRATOR" = "false" ]; then
    echo -e "${RED}⏭️  MIGRATOR${NC} - No migration changes"
  fi
fi
# Always rebuild migrator on main (note: on main branch)
if git rev-parse --abbrev-ref HEAD | grep -q "^main$"; then
  echo -e "${YELLOW}🔄 MIGRATOR${NC} - Always rebuild on main branch"
  REBUILD_MIGRATOR="true"
fi

# PROCESSOR
if check_pattern "PROCESSOR" '(Dockerfile\.processor|requirements-processor\.txt|src/pipeline/|src/ml/|src/services/classification_service\.py|src/cli/commands/analysis\.py|src/cli/commands/entity_extraction\.py|alembic/versions/)'; then
  echo -e "${GREEN}✅ PROCESSOR${NC} - ML/entity extraction/migration changes detected"
  REBUILD_PROCESSOR="true"
else
  if [ "$REBUILD_PROCESSOR" = "false" ]; then
    echo -e "${RED}⏭️  PROCESSOR${NC} - No processor changes"
  fi
fi

# API
if check_pattern "API" '(Dockerfile\.api|requirements-api\.txt|backend/|src/models/api_backend\.py|src/cli/commands/cleaning\.py|src/cli/commands/reports\.py)'; then
  echo -e "${GREEN}✅ API${NC} - API/backend changes detected"
  REBUILD_API="true"
else
  if [ "$REBUILD_API" = "false" ]; then
    echo -e "${RED}⏭️  API${NC} - No API changes"
  fi
fi

# CRAWLER
if check_pattern "CRAWLER" '(Dockerfile\.crawler|requirements-crawler\.txt|src/crawler/|src/services/|src/utils/|src/cli/commands/(discovery|verification|extraction|content_cleaning)\.py)'; then
  echo -e "${GREEN}✅ CRAWLER${NC} - Discovery/verification/extraction changes detected"
  REBUILD_CRAWLER="true"
else
  if [ "$REBUILD_CRAWLER" = "false" ]; then
    echo -e "${RED}⏭️  CRAWLER${NC} - No crawler changes"
  fi
fi

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}🚀 SERVICE BUILD PLAN${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"

# Count services
COUNT=0
SERVICES_TO_BUILD=""

if [ "$REBUILD_BASE" = "true" ]; then
  echo -e "  ${GREEN}✅${NC} base"
  ((COUNT++))
  SERVICES_TO_BUILD="$SERVICES_TO_BUILD base"
else
  echo -e "  ${RED}⏭️ ${NC} base (skipped)"
fi

if [ "$REBUILD_ML_BASE" = "true" ]; then
  echo -e "  ${GREEN}✅${NC} ml-base"
  ((COUNT++))
  SERVICES_TO_BUILD="$SERVICES_TO_BUILD ml-base"
else
  echo -e "  ${RED}⏭️ ${NC} ml-base (skipped)"
fi

if [ "$REBUILD_MIGRATOR" = "true" ]; then
  echo -e "  ${GREEN}✅${NC} migrator"
  ((COUNT++))
  SERVICES_TO_BUILD="$SERVICES_TO_BUILD migrator"
else
  echo -e "  ${RED}⏭️ ${NC} migrator (skipped)"
fi

if [ "$REBUILD_PROCESSOR" = "true" ]; then
  echo -e "  ${GREEN}✅${NC} processor"
  ((COUNT++))
  SERVICES_TO_BUILD="$SERVICES_TO_BUILD processor"
else
  echo -e "  ${RED}⏭️ ${NC} processor (skipped)"
fi

if [ "$REBUILD_API" = "true" ]; then
  echo -e "  ${GREEN}✅${NC} api"
  ((COUNT++))
  SERVICES_TO_BUILD="$SERVICES_TO_BUILD api"
else
  echo -e "  ${RED}⏭️ ${NC} api (skipped)"
fi

if [ "$REBUILD_CRAWLER" = "true" ]; then
  echo -e "  ${GREEN}✅${NC} crawler"
  ((COUNT++))
  SERVICES_TO_BUILD="$SERVICES_TO_BUILD crawler"
else
  echo -e "  ${RED}⏭️ ${NC} crawler (skipped)"
fi

echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${GREEN}📦 Summary: Building $COUNT service(s)${NC}"
echo -e "   Services:${SERVICES_TO_BUILD}"
echo ""

# Build dependency graph
echo -e "${YELLOW}🔗 Build Dependency Order:${NC}"
echo ""

if [ "$REBUILD_BASE" = "true" ]; then
  echo "  1️⃣  base"
fi

if [ "$REBUILD_ML_BASE" = "true" ]; then
  echo "  2️⃣  ml-base (after base)"
fi

if [ "$REBUILD_MIGRATOR" = "true" ]; then
  echo "  3️⃣  migrator (after base)"
fi

if [ "$REBUILD_PROCESSOR" = "true" ]; then
  echo "  4️⃣  processor (after ml-base, migrator)"
fi

if [ "$REBUILD_API" = "true" ]; then
  echo "  4️⃣  api (after base, migrator - parallel with processor)"
fi

if [ "$REBUILD_CRAWLER" = "true" ]; then
  echo "  4️⃣  crawler (after base, migrator - parallel with processor/api)"
fi

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo ""

# Export for scripting
if [ "${SCRIPT_MODE:-false}" = "true" ]; then
  echo "rebuild_base=$REBUILD_BASE"
  echo "rebuild_ml_base=$REBUILD_ML_BASE"
  echo "rebuild_migrator=$REBUILD_MIGRATOR"
  echo "rebuild_processor=$REBUILD_PROCESSOR"
  echo "rebuild_api=$REBUILD_API"
  echo "rebuild_crawler=$REBUILD_CRAWLER"
  echo "services_to_build=$SERVICES_TO_BUILD"
  echo "service_count=$COUNT"
fi

echo -e "${GREEN}✅ Analysis complete!${NC}"
echo ""
echo "To see what files changed in detail:"
echo "  git diff --name-status $BASE_REF $HEAD_REF"
echo ""
echo "To see the actual diff:"
echo "  git diff $BASE_REF $HEAD_REF"
echo ""
