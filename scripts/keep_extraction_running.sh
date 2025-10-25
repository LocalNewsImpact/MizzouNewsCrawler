#!/bin/bash
# Script to keep extraction running until backlog is cleared
# Usage: ./scripts/keep_extraction_running.sh

set -euo pipefail

NAMESPACE="production"
MIN_BACKLOG=100  # Stop when backlog is below this threshold

echo "🚀 Starting continuous extraction until backlog is cleared..."
echo "Will stop when ready_for_extraction < ${MIN_BACKLOG}"
echo ""

iteration=1
while true; do
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Iteration ${iteration}: $(date)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # Check backlog via pipeline-status
    echo "📊 Checking pipeline status..."
    processor_pod=$(kubectl get pods -n ${NAMESPACE} -l app=mizzou-processor -o jsonpath='{.items[0].metadata.name}')
    
    backlog=$(kubectl exec -n ${NAMESPACE} ${processor_pod} -- python -m src.cli.cli_modular pipeline-status 2>&1 | grep "Ready for extraction:" | awk '{print $4}' || echo "0")
    
    echo "   Backlog: ${backlog} articles"
    
    if [ "${backlog}" -lt "${MIN_BACKLOG}" ]; then
        echo "✅ Backlog cleared! (${backlog} < ${MIN_BACKLOG})"
        echo "🎉 Extraction complete!"
        break
    fi
    
    # Submit new extraction workflow
    echo "🔄 Submitting extraction workflow..."
    workflow_name=$(cat <<'WORKFLOW_EOF' | kubectl create -n ${NAMESPACE} -f - -o jsonpath='{.metadata.name}'
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  generateName: extraction-backlog-
  labels:
    workflow-type: extraction-backlog
spec:
  serviceAccountName: argo-workflow
  entrypoint: extraction-backlog
  templates:
  - name: extraction-backlog
    metadata:
      labels:
        stage: extraction
    retryStrategy:
      limit: 2
      retryPolicy: "OnFailure"
      backoff:
        duration: "2m"
        factor: 2
    container:
      image: us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/processor:4b7cd1e
      imagePullPolicy: Always
      command: [python, -m, src.cli.cli_modular]
      args:
      - extract
      - --dataset
      - "Mizzou-Missouri-State"
      - --limit
      - "200"
      - --batches
      - "50"
      envFrom:
      - secretRef:
          name: origin-proxy-credentials
      env:
      - name: DATABASE_ENGINE
        value: "postgresql+psycopg2"
      - name: DATABASE_HOST
        value: "127.0.0.1"
      - name: DATABASE_PORT
        value: "5432"
      - name: DATABASE_USER
        valueFrom:
          secretKeyRef:
            name: cloudsql-db-credentials
            key: username
      - name: DATABASE_PASSWORD
        valueFrom:
          secretKeyRef:
            name: cloudsql-db-credentials
            key: password
      - name: DATABASE_NAME
        valueFrom:
          secretKeyRef:
            name: cloudsql-db-credentials
            key: database
      - name: DATABASE_URL
        value: "$(DATABASE_ENGINE)://$(DATABASE_USER):$(DATABASE_PASSWORD)@$(DATABASE_HOST):$(DATABASE_PORT)/$(DATABASE_NAME)"
      - name: USE_CLOUD_SQL_CONNECTOR
        value: "true"
      - name: CLOUD_SQL_INSTANCE
        value: "mizzou-news-crawler:us-central1:mizzou-db-prod"
      - name: LOG_LEVEL
        value: INFO
      resources:
        requests:
          memory: "4Gi"
          cpu: "2000m"
        limits:
          memory: "8Gi"
          cpu: "4000m"
    sidecars:
    - name: cloud-sql-proxy
      image: gcr.io/cloud-sql-connectors/cloud-sql-proxy:2.8.0
      args:
        - "--structured-logs"
        - "--port=5432"
        - "mizzou-news-crawler:us-central1:mizzou-db-prod"
      securityContext:
        runAsNonRoot: true
      resources:
        requests:
          memory: "256Mi"
          cpu: "100m"
        limits:
          memory: "512Mi"
          cpu: "500m"
WORKFLOW_EOF
    )
    
    echo "   Workflow: ${workflow_name}"
    
    # Wait for workflow to complete
    echo "⏳ Waiting for workflow to complete..."
    kubectl wait --for=condition=Completed --timeout=2h workflow/${workflow_name} -n ${NAMESPACE} || {
        status=$(kubectl get workflow ${workflow_name} -n ${NAMESPACE} -o jsonpath='{.status.phase}')
        if [ "${status}" == "Failed" ]; then
            echo "❌ Workflow failed, but continuing to next iteration..."
        fi
    }
    
    # Get final status
    final_status=$(kubectl get workflow ${workflow_name} -n ${NAMESPACE} -o jsonpath='{.status.phase}')
    echo "   Final status: ${final_status}"
    
    # Brief pause before next iteration
    echo ""
    echo "💤 Waiting 30 seconds before next iteration..."
    sleep 30
    
    iteration=$((iteration + 1))
done

echo ""
echo "✨ All done! Backlog successfully cleared."
