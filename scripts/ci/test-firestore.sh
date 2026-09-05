#!/usr/bin/env bash
# make test-firestore: the proxy-router tests, against a Firestore emulator.
set -euo pipefail

: "${FIRESTORE_EMULATOR_HOST:?run this through make test-firestore, which starts the emulator}"
for _ in $(seq 1 30); do
    curl -sf "http://${FIRESTORE_EMULATOR_HOST}" >/dev/null 2>&1 && break
    sleep 1
done
curl -sf "http://${FIRESTORE_EMULATOR_HOST}" >/dev/null 2>&1 || {
    echo "Firestore emulator at ${FIRESTORE_EMULATOR_HOST} never became ready" >&2
    exit 1
}
pytest -v -m 'integration and proxy' --tb=short --no-cov
