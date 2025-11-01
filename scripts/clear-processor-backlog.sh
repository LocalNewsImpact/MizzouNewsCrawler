#!/bin/bash
set -e

# Clear Processor Backlog Script
# Runs entity extraction and classification in parallel batches to clear backlogs

COLOR_GREEN='\033[0;32m'
COLOR_BLUE='\033[0;34m'
COLOR_YELLOW='\033[1;33m'
COLOR_RED='\033[0;31m'
COLOR_RESET='\033[0m'

NAMESPACE="production"
ENTITY_BACKLOG=3192
CLASSIFICATION_BACKLOG=2737

# Configuration
ENTITY_BATCH_SIZE=500
CLASSIFICATION_BATCH_SIZE=500
CLASSIFICATION_PER_BATCH=32  # Batch size for ML model inference

echo -e "${COLOR_BLUE}========================================${COLOR_RESET}"
echo -e "${COLOR_BLUE}PROCESSOR BACKLOG CLEARANCE${COLOR_RESET}"
echo -e "${COLOR_BLUE}========================================${COLOR_RESET}"
echo -e "Entity Extraction Backlog: ${ENTITY_BACKLOG} articles"
echo -e "Classification Backlog: ${CLASSIFICATION_BACKLOG} articles"
echo -e ""
echo -e "Strategy:"
echo -e "  • Entity Extraction: Process in batches of ${ENTITY_BATCH_SIZE}"
echo -e "  • Classification: Process in batches of ${CLASSIFICATION_BATCH_SIZE}"
echo -e "  • Running both in parallel pods"
echo -e ""

# Calculate number of batches needed
ENTITY_BATCHES=$(( (ENTITY_BACKLOG + ENTITY_BATCH_SIZE - 1) / ENTITY_BATCH_SIZE ))
CLASS_BATCHES=$(( (CLASSIFICATION_BACKLOG + CLASSIFICATION_BATCH_SIZE - 1) / CLASSIFICATION_BATCH_SIZE ))

echo -e "Estimated batches:"
echo -e "  • Entity Extraction: ${ENTITY_BATCHES} batches"
echo -e "  • Classification: ${CLASS_BATCHES} batches"
echo -e ""

# Function to run entity extraction batch
run_entity_batch() {
    local batch_num=$1
    echo -e "${COLOR_YELLOW}[Entity Batch ${batch_num}/${ENTITY_BATCHES}] Starting...${COLOR_RESET}"
    
    kubectl run entity-extraction-batch-${batch_num} \
        --namespace=${NAMESPACE} \
        --image=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:latest \
        --restart=Never \
        --env="DATABASE_ENGINE=postgresql+psycopg2" \
        --env="DATABASE_HOST=127.0.0.1" \
        --env="DATABASE_PORT=5432" \
        --env="USE_CLOUD_SQL_CONNECTOR=true" \
        --env="CLOUD_SQL_INSTANCE=mizzou-news-crawler:us-central1:mizzou-db-prod" \
        --overrides='{
          "spec": {
            "serviceAccountName": "mizzou-app",
            "containers": [{
              "name": "entity-extraction-batch-'${batch_num}'",
              "image": "us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:latest",
              "command": ["python", "-m", "src.cli.main", "extract-entities", "--limit", "'${ENTITY_BATCH_SIZE}'"],
              "env": [
                {"name": "DATABASE_ENGINE", "value": "postgresql+psycopg2"},
                {"name": "DATABASE_HOST", "value": "127.0.0.1"},
                {"name": "DATABASE_PORT", "value": "5432"},
                {"name": "DATABASE_USER", "valueFrom": {"secretKeyRef": {"name": "cloudsql-db-credentials", "key": "username"}}},
                {"name": "DATABASE_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "cloudsql-db-credentials", "key": "password"}}},
                {"name": "DATABASE_NAME", "valueFrom": {"secretKeyRef": {"name": "cloudsql-db-credentials", "key": "database"}}},
                {"name": "DATABASE_URL", "value": "$(DATABASE_ENGINE)://$(DATABASE_USER):$(DATABASE_PASSWORD)@$(DATABASE_HOST):$(DATABASE_PORT)/$(DATABASE_NAME)"},
                {"name": "USE_CLOUD_SQL_CONNECTOR", "value": "true"},
                {"name": "CLOUD_SQL_INSTANCE", "value": "mizzou-news-crawler:us-central1:mizzou-db-prod"},
                {"name": "NO_PROXY", "value": "localhost,127.0.0.1,metadata.google.internal,huggingface.co,*.huggingface.co"}
              ],
              "resources": {
                "requests": {"cpu": "500m", "memory": "2Gi"},
                "limits": {"cpu": "1000m", "memory": "4Gi"}
              }
            }]
          }
        }'
    
    echo -e "${COLOR_GREEN}[Entity Batch ${batch_num}] Pod created${COLOR_RESET}"
}

# Function to run classification batch
run_classification_batch() {
    local batch_num=$1
    echo -e "${COLOR_YELLOW}[Classification Batch ${batch_num}/${CLASS_BATCHES}] Starting...${COLOR_RESET}"
    
    kubectl run classification-batch-${batch_num} \
        --namespace=${NAMESPACE} \
        --image=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:latest \
        --restart=Never \
        --overrides='{
          "spec": {
            "serviceAccountName": "mizzou-app",
            "containers": [{
              "name": "classification-batch-'${batch_num}'",
              "image": "us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:latest",
              "command": ["python", "-m", "src.cli.main", "analyze", "--limit", "'${CLASSIFICATION_BATCH_SIZE}'", "--batch-size", "'${CLASSIFICATION_PER_BATCH}'"],
              "env": [
                {"name": "DATABASE_ENGINE", "value": "postgresql+psycopg2"},
                {"name": "DATABASE_HOST", "value": "127.0.0.1"},
                {"name": "DATABASE_PORT", "value": "5432"},
                {"name": "DATABASE_USER", "valueFrom": {"secretKeyRef": {"name": "cloudsql-db-credentials", "key": "username"}}},
                {"name": "DATABASE_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "cloudsql-db-credentials", "key": "password"}}},
                {"name": "DATABASE_NAME", "valueFrom": {"secretKeyRef": {"name": "cloudsql-db-credentials", "key": "database"}}},
                {"name": "DATABASE_URL", "value": "$(DATABASE_ENGINE)://$(DATABASE_USER):$(DATABASE_PASSWORD)@$(DATABASE_HOST):$(DATABASE_PORT)/$(DATABASE_NAME)"},
                {"name": "USE_CLOUD_SQL_CONNECTOR", "value": "true"},
                {"name": "CLOUD_SQL_INSTANCE", "value": "mizzou-news-crawler:us-central1:mizzou-db-prod"},
                {"name": "NO_PROXY", "value": "localhost,127.0.0.1,metadata.google.internal,huggingface.co,*.huggingface.co"}
              ],
              "resources": {
                "requests": {"cpu": "1000m", "memory": "3Gi"},
                "limits": {"cpu": "2000m", "memory": "6Gi"}
              }
            }]
          }
        }'
    
    echo -e "${COLOR_GREEN}[Classification Batch ${batch_num}] Pod created${COLOR_RESET}"
}

# Clean up any existing batch pods
echo -e "${COLOR_YELLOW}Cleaning up any existing batch pods...${COLOR_RESET}"
kubectl delete pods -n ${NAMESPACE} -l job=backlog-clearance --ignore-not-found=true 2>/dev/null || true
echo -e ""

# Start batches (run 2 entity and 2 classification in parallel at a time)
echo -e "${COLOR_BLUE}========================================${COLOR_RESET}"
echo -e "${COLOR_BLUE}Starting Batch Processing${COLOR_RESET}"
echo -e "${COLOR_BLUE}========================================${COLOR_RESET}"
echo -e ""

# Launch initial batches
if [ ${ENTITY_BATCHES} -gt 0 ]; then
    run_entity_batch 1
    if [ ${ENTITY_BATCHES} -gt 1 ]; then
        sleep 5
        run_entity_batch 2
    fi
fi

if [ ${CLASS_BATCHES} -gt 0 ]; then
    sleep 5
    run_classification_batch 1
    if [ ${CLASS_BATCHES} -gt 1 ]; then
        sleep 5
        run_classification_batch 2
    fi
fi

echo -e ""
echo -e "${COLOR_BLUE}========================================${COLOR_RESET}"
echo -e "${COLOR_GREEN}✅ Batch pods launched!${COLOR_RESET}"
echo -e "${COLOR_BLUE}========================================${COLOR_RESET}"
echo -e ""
echo -e "Monitor progress:"
echo -e "  kubectl get pods -n ${NAMESPACE} | grep -E '(entity-extraction|classification)-batch'"
echo -e ""
echo -e "Check logs:"
echo -e "  kubectl logs -n ${NAMESPACE} entity-extraction-batch-1 -f"
echo -e "  kubectl logs -n ${NAMESPACE} classification-batch-1 -f"
echo -e ""
echo -e "Check pipeline status:"
echo -e "  kubectl exec -n ${NAMESPACE} mizzou-processor-5cbc976578-5fm6p -- python -c \\"
echo -e "    'from argparse import Namespace; from src.cli.commands.pipeline_status import handle_pipeline_status_command; \\"
echo -e "    handle_pipeline_status_command(Namespace(detailed=False, hours=24))'"
echo -e ""
echo -e "${COLOR_YELLOW}Note: This launched the first 2 batches of each type.${COLOR_RESET}"
echo -e "${COLOR_YELLOW}Monitor them and launch more batches as they complete.${COLOR_RESET}"
