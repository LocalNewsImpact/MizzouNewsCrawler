#!/bin/bash
# Build script for shared base Docker image
# Usage: ./scripts/build-base.sh [--no-cache] [--push]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
IMAGE_NAME="mizzou-base"
IMAGE_TAG="latest"
DOCKERFILE="Dockerfile.base"

# Parse arguments
NO_CACHE=""
PUSH=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --no-cache)
      NO_CACHE="--no-cache"
      shift
      ;;
    --push)
      PUSH=true
      shift
      ;;
    *)
      echo -e "${RED}Unknown option: $1${NC}"
      echo "Usage: $0 [--no-cache] [--push]"
      exit 1
      ;;
  esac
done

echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}Building Base Docker Image${NC}"
echo -e "${GREEN}================================${NC}"
echo ""
echo "Image: ${IMAGE_NAME}:${IMAGE_TAG}"
echo "Dockerfile: ${DOCKERFILE}"
echo "No cache: ${NO_CACHE:-(using cache)}"
echo "Push to registry: ${PUSH}"
echo ""

# Check if Dockerfile exists
if [ ! -f "$DOCKERFILE" ]; then
  echo -e "${RED}Error: $DOCKERFILE not found${NC}"
  exit 1
fi

# Check if requirements-base.txt exists
if [ ! -f "requirements-base.txt" ]; then
  echo -e "${RED}Error: requirements-base.txt not found${NC}"
  exit 1
fi

echo -e "${YELLOW}Step 1: Building base image...${NC}"
echo "This may take 5-10 minutes on first build, 2-3 minutes with cache"
echo ""

# Build the image
docker build ${NO_CACHE} \
  -t ${IMAGE_NAME}:${IMAGE_TAG} \
  -f ${DOCKERFILE} \
  .

if [ $? -ne 0 ]; then
  echo -e "${RED}Error: Build failed${NC}"
  exit 1
fi

echo ""
echo -e "${GREEN}✓ Build successful${NC}"
echo ""

# Show image details
echo -e "${YELLOW}Step 2: Image details${NC}"
docker images | grep -E "^(REPOSITORY|${IMAGE_NAME})"
echo ""

# Test the image
echo -e "${YELLOW}Step 3: Testing base image...${NC}"
echo "Testing package imports..."

docker run --rm ${IMAGE_NAME}:${IMAGE_TAG} python -c "
import pandas
import numpy
import sqlalchemy
import spacy
import requests
import pytest
print('✓ All base packages imported successfully')
" || {
  echo -e "${RED}Error: Package import test failed${NC}"
  exit 1
}

echo ""
echo "Testing spacy model..."

docker run --rm ${IMAGE_NAME}:${IMAGE_TAG} python -c "
import spacy
nlp = spacy.load('en_core_web_sm')
doc = nlp('This is a test sentence.')
assert len(doc) == 6
print('✓ Spacy model loaded and working')
" || {
  echo -e "${RED}Error: Spacy model test failed${NC}"
  exit 1
}

echo ""
echo -e "${GREEN}✓ All tests passed${NC}"
echo ""

# List installed packages
echo -e "${YELLOW}Step 4: Installed packages${NC}"
echo "Total packages:"
docker run --rm ${IMAGE_NAME}:${IMAGE_TAG} pip list | wc -l
echo ""
echo "Sample packages:"
docker run --rm ${IMAGE_NAME}:${IMAGE_TAG} pip list | head -15
echo "..."
echo ""

# Push to registry if requested
if [ "$PUSH" = true ]; then
  echo -e "${YELLOW}Step 5: Pushing to Artifact Registry...${NC}"
  
  # Check if gcloud is configured
  if ! command -v gcloud &> /dev/null; then
    echo -e "${RED}Error: gcloud not found. Install Google Cloud SDK first.${NC}"
    exit 1
  fi
  
  # Get project ID
  PROJECT_ID=$(gcloud config get-value project)
  if [ -z "$PROJECT_ID" ]; then
    echo -e "${RED}Error: No GCP project configured. Run: gcloud config set project PROJECT_ID${NC}"
    exit 1
  fi
  
  REGISTRY_IMAGE="us-central1-docker.pkg.dev/${PROJECT_ID}/mizzou-crawler/base:${IMAGE_TAG}"
  
  echo "Tagging image: ${REGISTRY_IMAGE}"
  docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${REGISTRY_IMAGE}
  
  echo "Pushing to Artifact Registry..."
  docker push ${REGISTRY_IMAGE}
  
  if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Image pushed successfully${NC}"
  else
    echo -e "${RED}Error: Push failed${NC}"
    exit 1
  fi
fi

echo ""
echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}Base Image Build Complete!${NC}"
echo -e "${GREEN}================================${NC}"
echo ""
echo "Next steps:"
echo "1. Build service images:"
echo "   docker build -t mizzou-api:latest -f Dockerfile.api ."
echo "   docker build -t mizzou-processor:latest -f Dockerfile.processor ."
echo "   docker build -t mizzou-crawler:latest -f Dockerfile.crawler ."
echo ""
echo "2. Test with docker-compose:"
echo "   docker-compose build"
echo "   docker-compose up -d"
echo ""
echo "3. Or push to Cloud Build:"
echo "   gcloud builds submit --config=cloudbuild-base.yaml"
echo ""
