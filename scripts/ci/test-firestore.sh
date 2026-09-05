#!/usr/bin/env bash
# make test-firestore: the proxy-router tests, against a Firestore emulator.
set -euo pipefail

: "${FIRESTORE_EMULATOR_HOST:?run this through make test-firestore, which starts the emulator}"
# Probed with Python, not curl: the CI image has no curl, and Python is
# the one tool every environment this script runs in is guaranteed to have.
ready() {
    python - "$FIRESTORE_EMULATOR_HOST" <<'PY'
import sys, urllib.request
urllib.request.urlopen(f"http://{sys.argv[1]}", timeout=2)
PY
}
for _ in $(seq 1 30); do
    ready >/dev/null 2>&1 && break
    sleep 1
done
ready >/dev/null 2>&1 || {
    echo "Firestore emulator at ${FIRESTORE_EMULATOR_HOST} never became ready" >&2
    exit 1
}
pytest -v -m 'integration and proxy' --tb=short --no-cov
