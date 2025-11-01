#!/bin/bash
set -e

# Sequential Processor Backlog Clearance
# Runs batches sequentially to avoid race conditions

COLOR_GREEN='\033[0;32m'
COLOR_BLUE='\033[0;34m'
COLOR_YELLOW='\033[1;33m'
COLOR_RED='\033[0;31m'
COLOR_RESET='\033[0m'

NAMESPACE="production"
PROCESSOR_POD="mizzou-processor-5cbc976578-5fm6p"

echo -e "${COLOR_BLUE}========================================${COLOR_RESET}"
echo -e "${COLOR_BLUE}SEQUENTIAL BACKLOG CLEARANCE${COLOR_RESET}"
echo -e "${COLOR_BLUE}========================================${COLOR_RESET}"
echo -e ""

# Function to wait for pod completion
wait_for_pod() {
    local pod_name=$1
    local max_wait=1800  # 30 minutes max
    local elapsed=0
    
    echo -e "${COLOR_YELLOW}Waiting for ${pod_name} to complete...${COLOR_RESET}"
    
    while [ $elapsed -lt $max_wait ]; do
        status=$(kubectl get pod -n ${NAMESPACE} ${pod_name} -o jsonpath='{.status.phase}' 2>/dev/null || echo "NotFound")
        
        if [ "$status" = "Succeeded" ]; then
            echo -e "${COLOR_GREEN}✅ ${pod_name} completed successfully${COLOR_RESET}"
            kubectl logs -n ${NAMESPACE} ${pod_name} --tail=10
            return 0
        elif [ "$status" = "Failed" ] || [ "$status" = "Error" ]; then
            echo -e "${COLOR_RED}❌ ${pod_name} failed${COLOR_RESET}"
            kubectl logs -n ${NAMESPACE} ${pod_name} --tail=20
            return 1
        elif [ "$status" = "NotFound" ]; then
            echo -e "${COLOR_RED}❌ ${pod_name} not found${COLOR_RESET}"
            return 1
        fi
        
        # Show progress every minute
        if [ $((elapsed % 60)) -eq 0 ]; then
            echo -e "  Status: ${status} (${elapsed}s elapsed)"
            # Show last log line
            kubectl logs -n ${NAMESPACE} ${pod_name} --tail=1 2>/dev/null || true
        fi
        
        sleep 10
        elapsed=$((elapsed + 10))
    done
    
    echo -e "${COLOR_RED}❌ ${pod_name} timed out after ${max_wait}s${COLOR_RESET}"
    return 1
}

# Function to run entity extraction batch and wait
run_entity_batch_sequential() {
    local batch_num=$1
    local batch_size=$2
    local pod_name="entity-batch-${batch_num}"
    
    echo -e ""
    echo -e "${COLOR_BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${COLOR_RESET}"
    echo -e "${COLOR_BLUE}Entity Extraction Batch ${batch_num}${COLOR_RESET}"
    echo -e "${COLOR_BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${COLOR_RESET}"
    
    # Delete if exists
    kubectl delete pod -n ${NAMESPACE} ${pod_name} --ignore-not-found=true 2>/dev/null || true
    sleep 2
    
    # Create pod
    kubectl run ${pod_name} \
        --namespace=${NAMESPACE} \
        --image=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:latest \
        --restart=Never \
        --overrides='{
          "spec": {
            "serviceAccountName": "mizzou-app",
            "containers": [{
              "name": "'${pod_name}'",
              "image": "us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:latest",
              "command": ["python", "-m", "src.cli.main", "extract-entities", "--limit", "'${batch_size}'"],
              "env": [
                {"name": "DATABASE_ENGINE", "value": "postgresql+psycopg2"},
                {"name": "DATABASE_HOST", "value": "127.0.0.1"},
                {"name": "DATABASE_PORT", "value": "5432"},
                {"name": "DATABASE_USER", "valueFrom": {"secretKeyRef": {"name": "cloudsql-db-credentials", "key": "username"}}},
                {"name": "DATABASE_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "cloudsql-db-credentials", "key": "password"}}},
                {"name": "DATABASE_NAME", "valueFrom": {"secretKeyRef": {"name": "cloudsql-db-credentials", "key": "database"}}},
                {"name": "DATABASE_URL", "value": "postgresql+psycopg2://$(DATABASE_USER):$(DATABASE_PASSWORD)@$(DATABASE_HOST):$(DATABASE_PORT)/$(DATABASE_NAME)"},
                {"name": "USE_CLOUD_SQL_CONNECTOR", "value": "true"},
                {"name": "CLOUD_SQL_INSTANCE", "value": "mizzou-news-crawler:us-central1:mizzou-db-prod"},
                {"name": "NO_PROXY", "value": "localhost,127.0.0.1,metadata.google.internal,huggingface.co,*.huggingface.co"}
              ],
              "resources": {
                "requests": {"cpu": "500m", "memory": "2Gi"},
                "limits": {"cpu": "1500m", "memory": "4Gi"}
              }
            }]
          }
        }' > /dev/null
    
    wait_for_pod ${pod_name}
    return $?
}

# Function to run classification batch and wait
run_classification_batch_sequential() {
    local batch_num=$1
    local batch_size=$2
    local inference_batch=$3
    local pod_name="class-batch-${batch_num}"
    
    echo -e ""
    echo -e "${COLOR_BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${COLOR_RESET}"
    echo -e "${COLOR_BLUE}Classification Batch ${batch_num}${COLOR_RESET}"
    echo -e "${COLOR_BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${COLOR_RESET}"
    
    # Delete if exists
    kubectl delete pod -n ${NAMESPACE} ${pod_name} --ignore-not-found=true 2>/dev/null || true
    sleep 2
    
    # Create pod
    kubectl run ${pod_name} \
        --namespace=${NAMESPACE} \
        --image=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:latest \
        --restart=Never \
        --overrides='{
          "spec": {
            "serviceAccountName": "mizzou-app",
            "containers": [{
              "name": "'${pod_name}'",
              "image": "us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:latest",
              "command": ["python", "-m", "src.cli.main", "analyze", "--limit", "'${batch_size}'", "--batch-size", "'${inference_batch}'"],
              "env": [
                {"name": "DATABASE_ENGINE", "value": "postgresql+psycopg2"},
                {"name": "DATABASE_HOST", "value": "127.0.0.1"},
                {"name": "DATABASE_PORT", "value": "5432"},
                {"name": "DATABASE_USER", "valueFrom": {"secretKeyRef": {"name": "cloudsql-db-credentials", "key": "username"}}},
                {"name": "DATABASE_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "cloudsql-db-credentials", "key": "password"}}},
                {"name": "DATABASE_NAME", "valueFrom": {"secretKeyRef": {"name": "cloudsql-db-credentials", "key": "database"}}},
                {"name": "DATABASE_URL", "value": "postgresql+psycopg2://$(DATABASE_USER):$(DATABASE_PASSWORD)@$(DATABASE_HOST):$(DATABASE_PORT)/$(DATABASE_NAME)"},
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
        }' > /dev/null
    
    wait_for_pod ${pod_name}
    return $?
}

# Get current backlog
echo -e "${COLOR_YELLOW}Checking current backlog...${COLOR_RESET}"
kubectl exec -n ${NAMESPACE} ${PROCESSOR_POD} -- python -c "
from argparse import Namespace
from src.cli.commands.pipeline_status import handle_pipeline_status_command
handle_pipeline_status_command(Namespace(detailed=False, hours=24))
" | grep -E "(Ready for entity|Ready for classification)" || true

echo -e ""
read -p "Continue with sequential processing? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${COLOR_YELLOW}Cancelled${COLOR_RESET}"
    exit 0
fi

# Run entity extraction batches
echo -e ""
echo -e "${COLOR_GREEN}========================================${COLOR_RESET}"
echo -e "${COLOR_GREEN}PHASE 1: ENTITY EXTRACTION${COLOR_RESET}"
echo -e "${COLOR_GREEN}========================================${COLOR_RESET}"

ENTITY_BATCH_SIZE=500
for i in {1..7}; do
    run_entity_batch_sequential $i $ENTITY_BATCH_SIZE || {
        echo -e "${COLOR_RED}Stopping due to failure${COLOR_RESET}"
        exit 1
    }
done

# Run classification batches
echo -e ""
echo -e "${COLOR_GREEN}========================================${COLOR_RESET}"
echo -e "${COLOR_GREEN}PHASE 2: CLASSIFICATION${COLOR_RESET}"
echo -e "${COLOR_GREEN}========================================${COLOR_RESET}"

CLASS_BATCH_SIZE=500
CLASS_INFERENCE_BATCH=32
for i in {1..6}; do
    run_classification_batch_sequential $i $CLASS_BATCH_SIZE $CLASS_INFERENCE_BATCH || {
        echo -e "${COLOR_RED}Stopping due to failure${COLOR_RESET}"
        exit 1
    }
done

echo -e ""
echo -e "${COLOR_GREEN}========================================${COLOR_RESET}"
echo -e "${COLOR_GREEN}✅ ALL BATCHES COMPLETED!${COLOR_RESET}"
echo -e "${COLOR_GREEN}========================================${COLOR_RESET}"
echo -e ""

# Final status check
echo -e "${COLOR_YELLOW}Final pipeline status:${COLOR_RESET}"
kubectl exec -n ${NAMESPACE} ${PROCESSOR_POD} -- python -c "
from argparse import Namespace
from src.cli.commands.pipeline_status import handle_pipeline_status_command
handle_pipeline_status_command(Namespace(detailed=False, hours=24))
"
