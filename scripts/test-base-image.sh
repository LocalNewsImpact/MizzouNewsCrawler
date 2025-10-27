#!/bin/bash
# Test script for base image implementation
# Validates that all requirements are properly split and Dockerfiles are correct

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}Base Image Implementation Tests${NC}"
echo -e "${BLUE}================================${NC}"
echo ""

ERRORS=0
WARNINGS=0

# Test 1: Check all required files exist
echo -e "${YELLOW}Test 1: Checking required files...${NC}"
REQUIRED_FILES=(
    "Dockerfile.base"
    "requirements-base.txt"
    "requirements-api.txt"
    "requirements-processor.txt"
    "requirements-crawler.txt"
    "gcp/cloudbuild/cloudbuild-base.yaml"
    "gcp/triggers/trigger-base.yaml"
    "scripts/build-base.sh"
    "docs/BASE_IMAGE_MAINTENANCE.md"
    "docs/issues/shared-base-image-optimization.md"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo -e "  ${GREEN}✓${NC} $file exists"
    else
        echo -e "  ${RED}✗${NC} $file missing"
        ((ERRORS++))
    fi
done
echo ""

# Test 2: Verify requirements coverage
echo -e "${YELLOW}Test 2: Verifying requirements coverage...${NC}"

# Extract package names from original requirements.txt
ORIGINAL_PACKAGES=$(cat requirements.txt | grep -v "^#" | grep -v "^$" | cut -d'>' -f1 | cut -d'=' -f1 | cut -d'[' -f1 | sort | uniq)
ORIGINAL_COUNT=$(echo "$ORIGINAL_PACKAGES" | wc -l)

# Extract package names from split requirements
SPLIT_PACKAGES=$(cat requirements-base.txt requirements-api.txt requirements-processor.txt requirements-crawler.txt | grep -v "^#" | grep -v "^$" | cut -d'>' -f1 | cut -d'=' -f1 | cut -d'[' -f1 | sort | uniq)
SPLIT_COUNT=$(echo "$SPLIT_PACKAGES" | wc -l)

echo "  Original requirements.txt: $ORIGINAL_COUNT packages"
echo "  Split requirements total: $SPLIT_COUNT packages"

# Check for missing packages
MISSING=$(comm -23 <(echo "$ORIGINAL_PACKAGES") <(echo "$SPLIT_PACKAGES"))
if [ -z "$MISSING" ]; then
    echo -e "  ${GREEN}✓${NC} All packages from requirements.txt are covered"
else
    echo -e "  ${RED}✗${NC} Missing packages:"
    echo "$MISSING" | sed 's/^/    /'
    ((ERRORS++))
fi

# Check for duplicate packages
DUPLICATES=$(cat requirements-base.txt requirements-api.txt requirements-processor.txt requirements-crawler.txt | grep -v "^#" | grep -v "^$" | cut -d'>' -f1 | cut -d'=' -f1 | cut -d'[' -f1 | sort | uniq -d)
if [ -z "$DUPLICATES" ]; then
    echo -e "  ${GREEN}✓${NC} No duplicate packages across split files"
else
    echo -e "  ${YELLOW}⚠${NC} Duplicate packages found:"
    echo "$DUPLICATES" | sed 's/^/    /'
    ((WARNINGS++))
fi

# Show distribution
BASE_COUNT=$(cat requirements-base.txt | grep -v "^#" | grep -v "^$" | wc -l)
API_COUNT=$(cat requirements-api.txt | grep -v "^#" | grep -v "^$" | wc -l)
PROCESSOR_COUNT=$(cat requirements-processor.txt | grep -v "^#" | grep -v "^$" | wc -l)
CRAWLER_COUNT=$(cat requirements-crawler.txt | grep -v "^#" | grep -v "^$" | wc -l)

echo ""
echo "  Package distribution:"
echo "    Base: $BASE_COUNT packages (~${BASE_COUNT}/${SPLIT_COUNT} = $(( BASE_COUNT * 100 / SPLIT_COUNT ))%)"
echo "    API: $API_COUNT packages"
echo "    Processor: $PROCESSOR_COUNT packages"
echo "    Crawler: $CRAWLER_COUNT packages"
echo ""

# Test 3: Check Dockerfile.base structure
echo -e "${YELLOW}Test 3: Validating Dockerfile.base...${NC}"

if grep -q "FROM python:3.11-slim" Dockerfile.base; then
    echo -e "  ${GREEN}✓${NC} Uses correct base image (python:3.11-slim)"
else
    echo -e "  ${RED}✗${NC} Missing or incorrect base image"
    ((ERRORS++))
fi

if grep -q "COPY requirements-base.txt" Dockerfile.base; then
    echo -e "  ${GREEN}✓${NC} Copies requirements-base.txt"
else
    echo -e "  ${RED}✗${NC} Doesn't copy requirements-base.txt"
    ((ERRORS++))
fi

if grep -q "pip install.*requirements-base.txt" Dockerfile.base; then
    echo -e "  ${GREEN}✓${NC} Installs base requirements"
else
    echo -e "  ${RED}✗${NC} Doesn't install base requirements"
    ((ERRORS++))
fi

if grep -q "spacy download en_core_web_sm" Dockerfile.base; then
    echo -e "  ${GREEN}✓${NC} Downloads spacy model"
else
    echo -e "  ${RED}✗${NC} Doesn't download spacy model"
    ((ERRORS++))
fi

if grep -q "useradd.*appuser" Dockerfile.base; then
    echo -e "  ${GREEN}✓${NC} Creates non-root user"
else
    echo -e "  ${RED}✗${NC} Doesn't create non-root user"
    ((ERRORS++))
fi
echo ""

# Test 4: Check service Dockerfiles
echo -e "${YELLOW}Test 4: Validating service Dockerfiles...${NC}"

for dockerfile in Dockerfile.api Dockerfile.processor Dockerfile.crawler; do
    echo "  Checking $dockerfile:"
    
    if grep -q "ARG BASE_IMAGE" "$dockerfile"; then
        echo -e "    ${GREEN}✓${NC} Has BASE_IMAGE ARG"
    else
        echo -e "    ${RED}✗${NC} Missing BASE_IMAGE ARG"
        ((ERRORS++))
    fi
    
    if grep -q 'FROM ${BASE_IMAGE}' "$dockerfile" || grep -q 'FROM \${BASE_IMAGE}' "$dockerfile"; then
        echo -e "    ${GREEN}✓${NC} Uses BASE_IMAGE variable"
    else
        echo -e "    ${RED}✗${NC} Doesn't use BASE_IMAGE variable"
        ((ERRORS++))
    fi
    
    # Check if it installs service-specific requirements
    service=$(basename "$dockerfile" .Dockerfile | sed 's/Dockerfile.//')
    if grep -q "requirements-${service}.txt" "$dockerfile"; then
        echo -e "    ${GREEN}✓${NC} Installs service-specific requirements"
    else
        echo -e "    ${YELLOW}⚠${NC} May not install service-specific requirements"
        ((WARNINGS++))
    fi
done
echo ""

# Test 5: Check Cloud Build configs
echo -e "${YELLOW}Test 5: Validating Cloud Build configurations...${NC}"

# Check base Cloud Build config
if grep -q "Dockerfile.base" gcp/cloudbuild/cloudbuild-base.yaml; then
    echo -e "  ${GREEN}✓${NC} gcp/cloudbuild/cloudbuild-base.yaml references Dockerfile.base"
else
    echo -e "  ${RED}✗${NC} gcp/cloudbuild/cloudbuild-base.yaml doesn't reference Dockerfile.base"
    ((ERRORS++))
fi

# Check service Cloud Build configs
for config in gcp/cloudbuild/cloudbuild-api-only.yaml gcp/cloudbuild/cloudbuild-processor-only.yaml gcp/cloudbuild/cloudbuild-crawler-only.yaml; do
    echo "  Checking $config:"
    
    if grep -q "_BASE_IMAGE" "$config"; then
        echo -e "    ${GREEN}✓${NC} Has BASE_IMAGE substitution"
    else
        echo -e "    ${RED}✗${NC} Missing BASE_IMAGE substitution"
        ((ERRORS++))
    fi
    
    if grep -q "BASE_IMAGE=\${_BASE_IMAGE}" "$config" || grep -q 'BASE_IMAGE=${_BASE_IMAGE}' "$config"; then
        echo -e "    ${GREEN}✓${NC} Uses BASE_IMAGE build arg"
    else
        echo -e "    ${RED}✗${NC} Doesn't use BASE_IMAGE build arg"
        ((ERRORS++))
    fi
    
    # Check if timeout was reduced (should be 300s instead of 900s)
    if grep -q "timeout.*300s" "$config" || grep -q "timeout.*'300s'" "$config"; then
        echo -e "    ${GREEN}✓${NC} Timeout reduced to 300s (5 min)"
    else
        TIMEOUT=$(grep "timeout" "$config" || echo "not found")
        echo -e "    ${YELLOW}⚠${NC} Timeout not optimally set: $TIMEOUT"
        ((WARNINGS++))
    fi
done
echo ""

# Test 6: Check docker-compose.yml
echo -e "${YELLOW}Test 6: Validating docker-compose.yml...${NC}"

if grep -q "dockerfile: Dockerfile.base" docker-compose.yml; then
    echo -e "  ${GREEN}✓${NC} Has base image service definition"
else
    echo -e "  ${YELLOW}⚠${NC} No base image service (optional)"
    ((WARNINGS++))
fi

if grep -q "BASE_IMAGE" docker-compose.yml; then
    echo -e "  ${GREEN}✓${NC} Services use BASE_IMAGE build arg"
else
    echo -e "  ${RED}✗${NC} Services don't use BASE_IMAGE build arg"
    ((ERRORS++))
fi
echo ""

# Test 7: Check documentation
echo -e "${YELLOW}Test 7: Validating documentation...${NC}"

if [ -f "docs/BASE_IMAGE_MAINTENANCE.md" ]; then
    if grep -q "When to Rebuild" docs/BASE_IMAGE_MAINTENANCE.md; then
        echo -e "  ${GREEN}✓${NC} BASE_IMAGE_MAINTENANCE.md has rebuild guide"
    else
        echo -e "  ${YELLOW}⚠${NC} BASE_IMAGE_MAINTENANCE.md missing rebuild guide"
        ((WARNINGS++))
    fi
    
    if grep -q "Rollback" docs/BASE_IMAGE_MAINTENANCE.md; then
        echo -e "  ${GREEN}✓${NC} BASE_IMAGE_MAINTENANCE.md has rollback procedure"
    else
        echo -e "  ${YELLOW}⚠${NC} BASE_IMAGE_MAINTENANCE.md missing rollback procedure"
        ((WARNINGS++))
    fi
fi

if [ -f "docs/DOCKER_GUIDE.md" ]; then
    if grep -q "base image\|Base Image" docs/DOCKER_GUIDE.md; then
        echo -e "  ${GREEN}✓${NC} DOCKER_GUIDE.md updated with base image info"
    else
        echo -e "  ${YELLOW}⚠${NC} DOCKER_GUIDE.md may need base image documentation"
        ((WARNINGS++))
    fi
fi

if [ -f "docs/issues/shared-base-image-optimization.md" ]; then
    echo -e "  ${GREEN}✓${NC} Roadmap document exists"
else
    echo -e "  ${RED}✗${NC} Roadmap document missing"
    ((ERRORS++))
fi
echo ""

# Test 8: Build script check
echo -e "${YELLOW}Test 8: Validating build script...${NC}"

if [ -f "scripts/build-base.sh" ]; then
    if [ -x "scripts/build-base.sh" ]; then
        echo -e "  ${GREEN}✓${NC} build-base.sh is executable"
    else
        echo -e "  ${YELLOW}⚠${NC} build-base.sh not executable (run: chmod +x scripts/build-base.sh)"
        ((WARNINGS++))
    fi
    
    if grep -q "docker build" scripts/build-base.sh && grep -q "DOCKERFILE.*base" scripts/build-base.sh; then
        echo -e "  ${GREEN}✓${NC} build-base.sh builds base image"
    else
        echo -e "  ${RED}✗${NC} build-base.sh doesn't build base image"
        ((ERRORS++))
    fi
else
    echo -e "  ${RED}✗${NC} build-base.sh missing"
    ((ERRORS++))
fi
echo ""

# Summary
echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}Test Summary${NC}"
echo -e "${BLUE}================================${NC}"
echo ""

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✓ All tests passed!${NC}"
    echo ""
    echo "The base image optimization implementation is complete and ready for:"
    echo "  1. Local testing (build base image and services)"
    echo "  2. Integration testing with docker-compose"
    echo "  3. Deployment to Cloud Build"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠ Tests passed with $WARNINGS warning(s)${NC}"
    echo ""
    echo "The implementation is functional but has minor issues to address."
    exit 0
else
    echo -e "${RED}✗ Tests failed with $ERRORS error(s) and $WARNINGS warning(s)${NC}"
    echo ""
    echo "Please fix the errors before proceeding."
    exit 1
fi
