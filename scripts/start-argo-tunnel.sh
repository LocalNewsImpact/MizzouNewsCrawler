#!/bin/bash
# Launch a background port-forward to the Argo Workflows UI

set -euo pipefail

PORT=${ARGO_PORT:-2746}
PID_FILE=${ARGO_TUNNEL_PID_FILE:-/tmp/argo-port-forward.pid}
LOG_DIR=${ARGO_TUNNEL_LOG_DIR:-logs}
LOG_FILE=${LOG_DIR}/argo-port-forward.log
SERVICE=${ARGO_SERVICE:-}

mkdir -p "${LOG_DIR}"

if [[ -z "${SERVICE}" ]]; then
    # Auto-detect Argo server service by label, fall back to common names
    SERVICE=$(kubectl get svc -n argo -l app.kubernetes.io/name=argo-server \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)

    if [[ -z "${SERVICE}" ]]; then
        if kubectl get svc -n argo argo-workflows-server >/dev/null 2>&1; then
            SERVICE=argo-workflows-server
        elif kubectl get svc -n argo argo-server >/dev/null 2>&1; then
            SERVICE=argo-server
        fi
    fi

    if [[ -z "${SERVICE}" ]]; then
        echo "Could not find an Argo server service in namespace 'argo'."
        echo "Set ARGO_SERVICE to the correct service name and retry."
        exit 1
    fi
fi

echo "Using Argo service: ${SERVICE}"

if [[ -f "${PID_FILE}" ]]; then
    EXISTING_PID=$(cat "${PID_FILE}")
    if ps -p "${EXISTING_PID}" >/dev/null 2>&1; then
        echo "An Argo port-forward is already running (PID ${EXISTING_PID})."
        echo "Stop it with: kill ${EXISTING_PID}"
        exit 1
    fi
    rm -f "${PID_FILE}"
fi

nohup kubectl -n argo port-forward "svc/${SERVICE}" "${PORT}:${PORT}" \
    >"${LOG_FILE}" 2>&1 &
PID=$!
echo "${PID}" >"${PID_FILE}"

echo "Argo UI available on http://localhost:${PORT}"
echo "Forwarding svc/${SERVICE} from namespace argo"
echo "Logs: ${LOG_FILE}"
echo "PID file: ${PID_FILE}"
