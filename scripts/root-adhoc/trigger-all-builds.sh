#!/bin/bash

# Trigger remaining builds in dependency order with 5-minute delays
# Base was already built, this handles ML-base -> API -> Crawler -> Processor

echo "Starting remaining build triggers..."
echo "==============================================="

# Build 1: ML Base (depends on base which was already built)
echo ""
echo "Triggering ML-base build..."
gcloud builds triggers run build-ml-base-manual --branch=main --project=mizzou-news-crawler
echo "ML-base build started at $(date)"
echo "Waiting 5 minutes before next build..."
sleep 300

# Build 2: API
echo ""
echo "Triggering API build..."
gcloud builds triggers run build-api-manual --branch=main --project=mizzou-news-crawler
echo "API build started at $(date)"
echo "Waiting 5 minutes before next build..."
sleep 300

# Build 3: Crawler
echo ""
echo "Triggering Crawler build..."
gcloud builds triggers run build-crawler-manual --branch=main --project=mizzou-news-crawler
echo "Crawler build started at $(date)"
echo "Waiting 5 minutes before next build..."
sleep 300

# Build 4: Processor
echo ""
echo "Triggering Processor build..."
gcloud builds triggers run build-processor-manual --branch=main --project=mizzou-news-crawler
echo "Processor build started at $(date)"

echo ""
echo "==============================================="
echo "All remaining builds triggered successfully!"
echo "Check progress at: https://console.cloud.google.com/cloud-build/builds?project=mizzou-news-crawler"
