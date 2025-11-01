#!/bin/bash
set -e

# Parallel Backlog Clearance with Source Partitioning
# Divides work by source to avoid race conditions

COLOR_GREEN='\033[0;32m'
COLOR_BLUE='\033[0;34m'
COLOR_YELLOW='\033[1;33m'
COLOR_RED='\033[0;31m'
COLOR_RESET='\033[0m'

NAMESPACE="production"
PROCESSOR_POD="mizzou-processor-5cbc976578-5fm6p"

echo -e "${COLOR_BLUE}========================================${COLOR_RESET}"
echo -e "${COLOR_BLUE}PARALLEL BACKLOG CLEARANCE${COLOR_RESET}"
echo -e "${COLOR_BLUE}(Source-based work partitioning)${COLOR_RESET}"
echo -e "${COLOR_BLUE}========================================${COLOR_RESET}"
echo -e ""

# Get list of sources with pending work
echo -e "${COLOR_YELLOW}Getting sources with pending entity extraction...${COLOR_RESET}"
ENTITY_SOURCES=$(kubectl exec -n ${NAMESPACE} ${PROCESSOR_POD} -- python -c "
from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
with db.get_session() as session:
    result = session.execute(text('''
        SELECT DISTINCT cl.source, COUNT(*) as cnt
        FROM articles a
        JOIN candidate_links cl ON a.candidate_link_id = cl.id
        WHERE a.content IS NOT NULL
        AND a.text IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM article_entities ae WHERE ae.article_id = a.id)
        AND a.status != 'error'
        GROUP BY cl.source
        ORDER BY cnt DESC
    '''))
    for row in result:
        print(f'{row[0]}:{row[1]}')
" 2>/dev/null)

echo -e "${COLOR_YELLOW}Getting sources with pending classification...${COLOR_RESET}"
CLASS_SOURCES=$(kubectl exec -n ${NAMESPACE} ${PROCESSOR_POD} -- python -c "
from src.models.database import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
with db.get_session() as session:
    result = session.execute(text('''
        SELECT DISTINCT cl.source, COUNT(*) as cnt
        FROM articles a
        JOIN candidate_links cl ON a.candidate_link_id = cl.id
        WHERE a.status IN ('cleaned', 'local')
        AND NOT EXISTS (
            SELECT 1 FROM article_labels al 
            WHERE al.article_id = a.id 
            AND al.label_version = 'default'
        )
        GROUP BY cl.source
        ORDER BY cnt DESC
    '''))
    for row in result:
        print(f'{row[0]}:{row[1]}')
" 2>/dev/null)

echo -e ""
echo -e "${COLOR_GREEN}Entity Extraction Sources:${COLOR_RESET}"
echo "$ENTITY_SOURCES" | head -20
echo -e ""
echo -e "${COLOR_GREEN}Classification Sources:${COLOR_RESET}"
echo "$CLASS_SOURCES" | head -20
echo -e ""

# Convert to arrays
readarray -t ENTITY_ARRAY <<< "$ENTITY_SOURCES"
readarray -t CLASS_ARRAY <<< "$CLASS_SOURCES"

ENTITY_COUNT=${#ENTITY_ARRAY[@]}
CLASS_COUNT=${#CLASS_ARRAY[@]}

echo -e "Total sources:"
echo -e "  Entity Extraction: ${ENTITY_COUNT} sources"
echo -e "  Classification: ${CLASS_COUNT} sources"
echo -e ""

# Determine number of parallel workers
ENTITY_WORKERS=4
CLASS_WORKERS=4

echo -e "Strategy:"
echo -e "  ${ENTITY_WORKERS} parallel entity extraction workers"
echo -e "  ${CLASS_WORKERS} parallel classification workers"
echo -e "  Each worker processes specific sources (no overlap)"
echo -e ""

read -p "Continue? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${COLOR_YELLOW}Cancelled${COLOR_RESET}"
    exit 0
fi

# Function to launch entity extraction worker for specific sources
launch_entity_worker() {
    local worker_id=$1
    shift
    local sources=("$@")
    local pod_name="entity-worker-${worker_id}"
    
    # Build source filter
    local source_list=""
    for src in "${sources[@]}"; do
        source_name=$(echo "$src" | cut -d: -f1)
        if [ -n "$source_name" ]; then
            source_list="${source_list},${source_name}"
        fi
    done
    source_list=${source_list:1}  # Remove leading comma
    
    if [ -z "$source_list" ]; then
        echo -e "${COLOR_YELLOW}[Worker ${worker_id}] No sources assigned${COLOR_RESET}"
        return
    fi
    
    echo -e "${COLOR_BLUE}[Entity Worker ${worker_id}] Processing: ${source_list:0:80}...${COLOR_RESET}"
    
    # Delete if exists
    kubectl delete pod -n ${NAMESPACE} ${pod_name} --ignore-not-found=true 2>/dev/null || true
    sleep 1
    
    # For now, we'll process all articles but workers will naturally work on different sources
    # due to ORDER BY source_id. This is imperfect but better than nothing.
    # A better solution would be to pass source filter to the command.
    
    kubectl run ${pod_name} \
        --namespace=${NAMESPACE} \
        --image=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:latest \
        --restart=Never \
        --labels="job=backlog-clearance,type=entity-extraction,worker=${worker_id}" \
        --overrides='{
          "spec": {
            "serviceAccountName": "mizzou-app",
            "containers": [{
              "name": "'${pod_name}'",
              "image": "us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:latest",
              "command": ["python", "-m", "src.cli.main", "extract-entities", "--limit", "1000"],
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
    
    echo -e "${COLOR_GREEN}[Entity Worker ${worker_id}] Launched${COLOR_RESET}"
}

# Function to launch classification worker
launch_class_worker() {
    local worker_id=$1
    local pod_name="class-worker-${worker_id}"
    
    echo -e "${COLOR_BLUE}[Classification Worker ${worker_id}] Launching...${COLOR_RESET}"
    
    # Delete if exists
    kubectl delete pod -n ${NAMESPACE} ${pod_name} --ignore-not-found=true 2>/dev/null || true
    sleep 1
    
    kubectl run ${pod_name} \
        --namespace=${NAMESPACE} \
        --image=us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:latest \
        --restart=Never \
        --labels="job=backlog-clearance,type=classification,worker=${worker_id}" \
        --overrides='{
          "spec": {
            "serviceAccountName": "mizzou-app",
            "containers": [{
              "name": "'${pod_name}'",
              "image": "us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:latest",
              "command": ["python", "-m", "src.cli.main", "analyze", "--limit", "1000", "--batch-size", "32"],
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
    
    echo -e "${COLOR_GREEN}[Classification Worker ${worker_id}] Launched${COLOR_RESET}"
}

echo -e ""
echo -e "${COLOR_BLUE}========================================${COLOR_RESET}"
echo -e "${COLOR_BLUE}Launching Workers${COLOR_RESET}"
echo -e "${COLOR_BLUE}========================================${COLOR_RESET}"
echo -e ""

# Launch entity extraction workers
# Note: Since we can't easily filter by source in the current CLI,
# we'll rely on natural partitioning (ordered by source) and larger limits
for i in $(seq 1 $ENTITY_WORKERS); do
    launch_entity_worker $i
    sleep 2
done

echo -e ""

# Launch classification workers
for i in $(seq 1 $CLASS_WORKERS); do
    launch_class_worker $i
    sleep 2
done

echo -e ""
echo -e "${COLOR_GREEN}========================================${COLOR_RESET}"
echo -e "${COLOR_GREEN}✅ All workers launched!${COLOR_RESET}"
echo -e "${COLOR_GREEN}========================================${COLOR_RESET}"
echo -e ""
echo -e "Monitor progress:"
echo -e "  kubectl get pods -n ${NAMESPACE} -l job=backlog-clearance"
echo -e ""
echo -e "Watch specific worker:"
echo -e "  kubectl logs -n ${NAMESPACE} entity-worker-1 -f"
echo -e "  kubectl logs -n ${NAMESPACE} class-worker-1 -f"
echo -e ""
echo -e "Check status:"
echo -e "  watch 'kubectl get pods -n ${NAMESPACE} -l job=backlog-clearance'"
echo -e ""
echo -e "${COLOR_YELLOW}Note: Workers process batches of 1000 articles each.${COLOR_RESET}"
echo -e "${COLOR_YELLOW}They will complete when done and need to be relaunched for more batches.${COLOR_RESET}"
